"""Load any source into the canonical ``core`` tables.

    rows (any source) -> staging.raw_records -> mapping -> validation -> upsert core.*

Imports are idempotent: rows are matched through ``core.external_refs`` (and, for
patients, by email/phone), so re-running the same export, or a nightly sync,
updates rather than duplicates. A bad row is recorded with its error and skipped;
it never fails the whole batch.

TODO(perf): row-by-row with a savepoint each is fine for exports up to ~100k
rows. Add a COPY-based bulk path when a client needs more.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import ValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from clinic_core.audit import audit
from clinic_core.database import current_tenant
from clinic_core.events import IMPORT_COMPLETED, emit
from clinic_db.models.core import (
    Appointment,
    Consent,
    ConsentKind,
    ExternalRef,
    Patient,
    Provider,
    Service,
    Tenant,
    Transaction,
)
from clinic_db.models.staging import ImportBatch, RawRecord
from clinic_integrations.canonical import (
    ENTITY_MODELS,
    AppointmentIn,
    PatientIn,
    ProviderIn,
    ServiceIn,
    TransactionIn,
)
from clinic_integrations.mapping import MappingConfig, MappingError, apply_mapping
from clinic_integrations.sources.base import Source

MAX_REPORTED_ERRORS = 100


class ImportBlocked(Exception):
    pass


@dataclass
class ImportResult:
    batch_id: uuid.UUID
    entity_type: str
    total: int = 0
    created: int = 0
    updated: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)
    error_count: int = 0

    def stats(self) -> dict[str, int]:
        return {"total": self.total, "created": self.created, "updated": self.updated, "errors": self.error_count}


def _jsonable(v: Any) -> Any:
    if isinstance(v, datetime | date):
        return v.isoformat()
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, uuid.UUID):
        return str(v)
    return v


class _Refs:
    """Resolves source-system ids and names to our row ids, with a per-batch cache."""

    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID, source_system: str):
        self.session, self.tenant_id, self.source_system = session, tenant_id, source_system
        self._ids: dict[tuple[str, str], uuid.UUID] = {}
        self._names: dict[tuple[type, str], Any] = {}

    async def find(self, entity_type: str, external_id: str | None) -> uuid.UUID | None:
        if not external_id:
            return None
        key = (entity_type, external_id)
        if key not in self._ids:
            found = await self.session.scalar(
                select(ExternalRef.entity_id).where(
                    ExternalRef.source_system == self.source_system,
                    ExternalRef.entity_type == entity_type,
                    ExternalRef.external_id == external_id,
                )
            )
            if found is None:
                return None
            self._ids[key] = found
        return self._ids[key]

    async def link(self, entity_type: str, external_id: str | None, entity_id: uuid.UUID) -> None:
        if not external_id or await self.find(entity_type, external_id):
            return
        self.session.add(
            ExternalRef(
                tenant_id=self.tenant_id,
                source_system=self.source_system,
                entity_type=entity_type,
                external_id=external_id,
                entity_id=entity_id,
            )
        )
        self._ids[(entity_type, external_id)] = entity_id

    async def named(self, model: type, name: str | None, **create_fields: Any) -> Any:
        """Find a provider/service by name (case-insensitive), creating it if new."""
        if not name:
            return None
        key = (model, name.strip().lower())
        if key not in self._names:
            obj = await self.session.scalar(select(model).where(func.lower(model.name) == key[1]).limit(1))
            if obj is None:
                obj = model(tenant_id=self.tenant_id, name=name.strip(), **create_fields)
                self.session.add(obj)
                await self.session.flush()
            self._names[key] = obj
        return self._names[key]


def _update(obj: Any, values: dict[str, Any]) -> None:
    """Fill in new information without blanking fields the source left empty."""
    for k, v in values.items():
        if v is not None:
            setattr(obj, k, v)


async def _record_consent(
    session: AsyncSession, tenant_id, patient_id, kind: str, granted: bool | None, batch_id: uuid.UUID
) -> None:
    if granted is None:
        return
    latest = await session.scalar(
        select(Consent.granted)
        .where(Consent.patient_id == patient_id, Consent.kind == kind)
        .order_by(Consent.recorded_at.desc())
        .limit(1)
    )
    if latest is None or latest != granted:
        session.add(
            Consent(
                tenant_id=tenant_id,
                patient_id=patient_id,
                kind=kind,
                granted=granted,
                source="import",
                evidence={"batch_id": str(batch_id)},
            )
        )


async def _load_patient(s: AsyncSession, refs: _Refs, rec: PatientIn, attrs: dict, batch_id) -> tuple[uuid.UUID, bool]:
    pid = await refs.find("patient", rec.external_id)
    if pid is None and (rec.email or rec.phone):
        conds = [
            c
            for c in (
                Patient.email == rec.email if rec.email else None,
                Patient.phone == rec.phone if rec.phone else None,
            )
            if c is not None
        ]
        pid = await s.scalar(select(Patient.id).where(or_(*conds)).limit(1))
    values = rec.model_dump(exclude={"external_id", "sms_opt_in", "email_opt_in"})
    created = pid is None
    if created:
        patient = Patient(tenant_id=refs.tenant_id, attributes=attrs, **values)
        s.add(patient)
        await s.flush()
    else:
        patient = await s.get(Patient, pid)
        _update(patient, values)
        patient.attributes = {**patient.attributes, **attrs}
    await refs.link("patient", rec.external_id, patient.id)
    await _record_consent(s, refs.tenant_id, patient.id, ConsentKind.SMS, rec.sms_opt_in, batch_id)
    await _record_consent(s, refs.tenant_id, patient.id, ConsentKind.EMAIL, rec.email_opt_in, batch_id)
    return patient.id, created


async def _load_provider(s, refs: _Refs, rec: ProviderIn, attrs, batch_id) -> tuple[uuid.UUID, bool]:
    pid = await refs.find("provider", rec.external_id)
    if pid:
        provider = await s.get(Provider, pid)
        _update(provider, {"name": rec.name, "credentials": rec.credentials})
        return pid, False
    provider = await refs.named(Provider, rec.name, credentials=rec.credentials, attributes=attrs)
    await refs.link("provider", rec.external_id, provider.id)
    return provider.id, True


async def _load_service(s, refs: _Refs, rec: ServiceIn, attrs, batch_id) -> tuple[uuid.UUID, bool]:
    values = {
        "name": rec.name,
        "category": rec.category,
        "default_price_cents": rec.price_cents,
        "duration_minutes": rec.duration_minutes,
    }
    sid = await refs.find("service", rec.external_id)
    service = await s.get(Service, sid) if sid else await refs.named(Service, rec.name, attributes=attrs)
    _update(service, values)
    await refs.link("service", rec.external_id, service.id)
    return service.id, sid is None


async def _load_appointment(s, refs: _Refs, rec: AppointmentIn, attrs, batch_id) -> tuple[uuid.UUID, bool]:
    patient_id = await refs.find("patient", rec.patient_external_id)
    if patient_id is None:
        raise MappingError(f"unknown patient {rec.patient_external_id!r} (import patients first)")
    provider_id = await refs.find("provider", rec.provider_external_id)
    if provider_id is None and rec.provider_name:
        provider_id = (await refs.named(Provider, rec.provider_name)).id
    service_id = await refs.find("service", rec.service_external_id)
    if service_id is None and rec.service_name:
        service_id = (await refs.named(Service, rec.service_name, category=rec.service_category)).id

    values = {
        "patient_id": patient_id,
        "provider_id": provider_id,
        "service_id": service_id,
        "starts_at": rec.starts_at,
        "ends_at": rec.ends_at,
        "status": rec.status,
    }
    aid = await refs.find("appointment", rec.external_id)
    if aid is None and rec.external_id is None:
        aid = await s.scalar(
            select(Appointment.id).where(Appointment.patient_id == patient_id, Appointment.starts_at == rec.starts_at)
        )
    if aid:
        appt = await s.get(Appointment, aid)
        _update(appt, values)
        appt.attributes = {**appt.attributes, **attrs}
        return aid, False
    appt = Appointment(tenant_id=refs.tenant_id, booked_via="import", attributes=attrs, **values)
    s.add(appt)
    await s.flush()
    await refs.link("appointment", rec.external_id, appt.id)
    return appt.id, True


async def _load_transaction(s, refs: _Refs, rec: TransactionIn, attrs, batch_id) -> tuple[uuid.UUID, bool]:
    patient_id = await refs.find("patient", rec.patient_external_id)
    if rec.patient_external_id and patient_id is None:
        raise MappingError(f"unknown patient {rec.patient_external_id!r} (import patients first)")
    service = await refs.named(Service, rec.service_name, category=rec.service_category)
    provider = await refs.named(Provider, rec.provider_name)
    values = {
        "patient_id": patient_id,
        "appointment_id": await refs.find("appointment", rec.appointment_external_id),
        "service_id": service.id if service else None,
        "provider_id": provider.id if provider else None,
        "amount_cents": rec.amount_cents,
        "kind": rec.kind,
        "occurred_at": rec.occurred_at,
    }
    tid = await refs.find("transaction", rec.external_id)
    if tid:
        txn = await s.get(Transaction, tid)
        _update(txn, values)
        return tid, False
    txn = Transaction(tenant_id=refs.tenant_id, attributes=attrs, **values)
    s.add(txn)
    await s.flush()
    await refs.link("transaction", rec.external_id, txn.id)
    return txn.id, True


_LOADERS = {
    "patient": _load_patient,
    "provider": _load_provider,
    "service": _load_service,
    "appointment": _load_appointment,
    "transaction": _load_transaction,
}


async def run_import(
    session: AsyncSession,
    *,
    source: Source,
    source_system: str,
    entity_type: str,
    mapping: MappingConfig,
    filename: str | None = None,
    actor_id: str = "system",
) -> ImportResult:
    if entity_type not in _LOADERS:
        raise ValueError(f"unsupported entity type {entity_type!r}")
    tenant_id = current_tenant(session)
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise ImportBlocked("unknown tenant")
    if tenant.baa_signed_at is None:
        raise ImportBlocked("A signed BAA is required before importing patient data")
    tz = ZoneInfo(mapping.timezone or tenant.timezone)

    batch = ImportBatch(
        tenant_id=tenant_id,
        source_system=source_system,
        source_kind=source.source_kind,
        entity_type=entity_type,
        filename=filename,
    )
    session.add(batch)
    await session.flush()

    result = ImportResult(batch_id=batch.id, entity_type=entity_type)
    refs = _Refs(session, tenant_id, source_system)
    model, loader = ENTITY_MODELS[entity_type], _LOADERS[entity_type]

    for row_number, row in enumerate(source.rows(), start=1):
        result.total += 1
        raw = RawRecord(
            tenant_id=tenant_id,
            batch_id=batch.id,
            row_number=row_number,
            data={k: _jsonable(v) for k, v in row.items()},
        )
        session.add(raw)
        try:
            async with session.begin_nested():
                values, attrs = apply_mapping(row, mapping, tz)
                rec = model.model_validate(values)
                raw.entity_id, created = await loader(session, refs, rec, attrs, batch.id)
            raw.status = "loaded"
            if created:
                result.created += 1
            else:
                result.updated += 1
        except (MappingError, ValidationError, DBAPIError) as e:
            refs._ids.clear()  # the savepoint rollback may have discarded cached refs
            refs._names.clear()
            raw.status, raw.error = "error", _short_error(e)
            result.error_count += 1
            if len(result.errors) < MAX_REPORTED_ERRORS:
                result.errors.append({"row": row_number, "error": raw.error})

    batch.status = "loaded"
    batch.stats = result.stats()
    batch.finished_at = datetime.now(UTC)
    await emit(
        session, IMPORT_COMPLETED, {"batch_id": str(batch.id), "entity_type": entity_type, "stats": result.stats()}
    )
    await audit(
        session,
        "data.import",
        actor_type="staff",
        actor_id=actor_id,
        entity_type="import_batch",
        entity_id=batch.id,
        details={"source_system": source_system, **result.stats()},
    )
    return result


def _short_error(e: Exception) -> str:
    if isinstance(e, ValidationError):
        return "; ".join(f"{'.'.join(map(str, err['loc'])) or 'row'}: {err['msg']}" for err in e.errors())
    if isinstance(e, DBAPIError):
        return f"database rejected row: {str(e.orig).splitlines()[0]}"
    return str(e)
