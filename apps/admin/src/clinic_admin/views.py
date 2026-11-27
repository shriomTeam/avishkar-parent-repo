"""Server-rendered pages. No scripts: every action is a form. Everything that comes from the database or the request
goes through ``esc`` before it reaches the page."""

from datetime import UTC, datetime
from html import escape as esc

from clinic_admin.service import STATUSES, FeatureInfo

STYLE = """
:root{--ink:#201d1d;--muted:#74717d;--line:#e8e7ec;--bg:#fafaf9;--card:#fff;--brand:#a1ff62;--brand-hover:#8ee84f;--brand-soft:#edffe1;--brand-ink:#315218;--focus:#80cc4e;--bad:#b3261e;--bad-hover:#8f1f19;--bad-soft:#ffedf0;--neutral-soft:#f1f0f3;--neutral-ink:#777180}
*{box-sizing:border-box}body{margin:0;font:15px/1.5 "Inter",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:var(--ink);background:var(--bg)}
header{background:#fff;border-bottom:1px solid var(--line);display:flex;gap:24px;align-items:center;padding:10px 24px}
header a{color:var(--ink);text-decoration:none}header a:hover{text-decoration:underline}
header .brand{display:flex;gap:10px;align-items:center;font-weight:700}header .brand img{width:30px;height:30px;border-radius:8px}
header .tag{background:var(--brand-soft);color:var(--brand-ink);border-radius:99px;padding:1px 9px;font-size:12px;font-weight:600}
header form{margin-left:auto}main{max-width:1100px;margin:0 auto;padding:24px}
h1{font-size:22px;margin:0 0 16px}h2{font-size:17px;margin:28px 0 10px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;margin-bottom:16px}
.stats{display:flex;gap:12px;flex-wrap:wrap}.stat{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 18px;min-width:130px}
.stat b{display:block;font-size:24px}table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:10px}
th,td{text-align:left;padding:9px 12px;border-bottom:1px solid var(--line);vertical-align:middle}th{font-size:12px;color:var(--muted);text-transform:uppercase}
.muted{color:var(--muted);font-size:13px}.pill{border-radius:99px;padding:2px 10px;font-size:12px;background:var(--neutral-soft);color:var(--neutral-ink)}
.on{background:var(--brand-soft);color:var(--brand-ink)}.off{background:var(--neutral-soft);color:var(--neutral-ink)}.suspended{background:var(--bad-soft);color:var(--bad)}
input,select,button{font:inherit;height:40px;line-height:1.2;padding:0 14px;border:1px solid var(--line);border-radius:9px;background:#fff;color:var(--ink)}
input:hover,select:hover{border-color:var(--brand)}
select{appearance:none;-webkit-appearance:none;padding:0 34px 0 12px;background-image:linear-gradient(45deg,transparent 50%,var(--ink) 50%),linear-gradient(135deg,var(--ink) 50%,transparent 50%);background-position:calc(100% - 17px) 17px,calc(100% - 12px) 17px;background-size:5px 5px,5px 5px;background-repeat:no-repeat}
input[type=checkbox]{width:18px;height:18px;padding:0;margin:0;accent-color:var(--brand-ink);cursor:pointer}
.row label{display:inline-flex;align-items:center;gap:8px}.card>.muted:first-child{margin:0 0 12px}.row button{align-self:center}
button{cursor:pointer;background:var(--brand);color:var(--ink);border-color:var(--brand)}button:hover{background:var(--brand-hover);border-color:var(--brand-hover)}
button.alt{background:#fff;color:var(--ink);border-color:var(--line)}button.alt:hover{border-color:var(--brand)}
button.danger{background:var(--bad);border-color:var(--bad);color:#fff}button.danger:hover{background:var(--bad-hover);border-color:var(--bad-hover)}
:is(a,input,select,button):focus-visible{outline:3px solid var(--focus);outline-offset:3px}
.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.error{background:var(--bad-soft);color:var(--bad);padding:10px 14px;border-radius:9px;margin-bottom:16px}
.notice{background:var(--brand-soft);color:var(--brand-ink);padding:10px 14px;border-radius:9px;margin-bottom:16px}
a{color:inherit}.login{max-width:360px;margin:12vh auto}.login input{width:100%;margin:6px 0 14px}
.login img{width:56px;height:56px;border-radius:14px;display:block;margin-bottom:12px}
@media(max-width:700px){main{padding:16px}table{display:block;overflow-x:auto}}
"""


def when(value: datetime | None) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC") if value else "—"


def layout(title: str, body: str, *, token: str | None = None, message: str = "", error: str = "") -> str:
    nav = ""
    if token is not None:
        nav = (
            '<header><span class="brand"><img src="/logo.png" alt="">Avishkar <span class="tag">Admin</span></span><a href="/">Clinics</a><a href="/audit">Admin log</a>'
            f'<form method="post" action="/logout"><input type="hidden" name="csrf" value="{esc(token)}">'
            '<button class="alt">Sign out</button></form></header>'
        )
    notices = (f'<div class="error">{esc(error)}</div>' if error else "") + (
        f'<div class="notice">{esc(message)}</div>' if message else ""
    )
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">'
        f"<title>{esc(title)} · Avishkar admin</title><style>{STYLE}</style></head><body>{nav}"
        f"<main>{notices}{body}</main></body></html>"
    )


def login_page(*, error: str = "") -> str:
    body = (
        '<div class="card login"><img src="/logo.png" alt=""><h1>Admin sign in</h1>'
        '<form method="post" action="/login"><label>User name<input name="username" autocomplete="username" required></label>'
        '<label>Password<input name="password" type="password" autocomplete="current-password" required></label>'
        "<button>Sign in</button></form></div>"
    )
    return layout("Sign in", body, error=error)


def _status_pill(status: str) -> str:
    return f'<span class="pill {"suspended" if status == "suspended" else ""}">{esc(status)}</span>'


def dashboard_page(
    stats: dict, clinics: list[dict], catalog: dict[str, FeatureInfo], *, query: str, status: str, token: str, **notice
) -> str:
    cards = f'<div class="stat"><b>{stats["total"]}</b>Clinics</div>' + "".join(
        f'<div class="stat"><b>{stats["by_status"].get(s, 0)}</b>{esc(s.capitalize())}</div>' for s in STATUSES
    )
    features = "".join(
        f"<tr><td>{esc(info.name)}<div class='muted'>{esc(key)}</div></td>"
        f"<td>{stats['feature_clinics'].get(key, 0)}</td><td>{'Yes' if info.available else 'Not released'}</td></tr>"
        for key, info in catalog.items()
    )
    options = '<option value="">Any status</option>' + "".join(
        f'<option value="{s}"{" selected" if s == status else ""}>{esc(s)}</option>' for s in STATUSES
    )
    rows = (
        "".join(
            f'<tr><td><a href="/clinics/{c["tenant"].id}">{esc(c["tenant"].name)}</a>'
            f'<div class="muted">{esc(c["tenant"].clinic_type)} · {esc(c["tenant"].timezone)}</div></td>'
            f"<td>{_status_pill(c['tenant'].status)}</td><td>{c['features']}</td><td>{c['staff']}</td>"
            f"<td>{when(c['tenant'].created_at)}</td></tr>"
            for c in clinics
        )
        or '<tr><td colspan="5" class="muted">No clinics match.</td></tr>'
    )
    body = (
        f'<h1>Clinics</h1><div class="stats">{cards}</div>'
        '<h2>Find a clinic</h2><form class="row" method="get" action="/">'
        f'<input name="q" value="{esc(query)}" placeholder="Clinic name" maxlength="100"><select name="status">{options}</select>'
        "<button>Search</button></form><br>"
        "<table><tr><th>Clinic</th><th>Status</th><th>Features on</th><th>Staff</th><th>Created</th></tr>"
        f"{rows}</table>"
        f"<h2>Features</h2><table><tr><th>Feature</th><th>Clinics with it on</th><th>Released</th></tr>{features}</table>"
    )
    return layout("Clinics", body, token=token, **notice)


def clinic_page(detail: dict, catalog: dict[str, FeatureInfo], *, token: str, **notice) -> str:
    tenant = detail["tenant"]
    cid = tenant.id
    hidden = f'<input type="hidden" name="csrf" value="{esc(token)}">'
    feature_rows = ""
    for key in sorted(set(catalog) | set(detail["features"])):
        info = catalog.get(key)
        row = detail["features"].get(key)
        on = key in detail["active_keys"]
        state = "On" if on else ("Expired" if row and row.enabled else "Off")
        expiry = f"ends {when(row.expires_at)}" if row and row.expires_at else ""
        if info:
            actions = (
                f'<form class="row" method="post" action="/clinics/{cid}/features/{esc(key)}">{hidden}'
                '<input type="date" name="expires" title="Optional end date">'
                '<button name="enabled" value="1">Turn on</button>'
                f'<button class="alt" name="enabled" value="0">Turn off</button></form>'
            )
        else:
            actions = '<span class="muted">Not installed here</span>'
        feature_rows += (
            f"<tr><td>{esc(info.name if info else key)}<div class='muted'>{esc(key)}</div></td>"
            f'<td><span class="pill {"on" if on else "off"}">{state}</span> <span class="muted">{esc(expiry)}</span></td>'
            f"<td>{actions}</td></tr>"
        )
    status_options = "".join(
        f'<option value="{s}"{" selected" if s == tenant.status else ""}>{esc(s)}</option>' for s in STATUSES
    )
    staff = (
        "".join(
            f"<tr><td>{esc(s.name)}</td><td>{esc(s.email)}</td><td>{esc(s.role)}</td><td>{'Yes' if s.active else 'No'}</td></tr>"
            for s in detail["staff"]
        )
        or '<tr><td colspan="4" class="muted">No staff.</td></tr>'
    )
    counts = "".join(f'<div class="stat"><b>{n}</b>{esc(label)}</div>' for label, n in detail["counts"].items())
    body = (
        f'<p><a href="/">← All clinics</a></p><h1>{esc(tenant.name)} {_status_pill(tenant.status)}</h1>'
        f'<p class="muted">{esc(tenant.clinic_type)} · {esc(tenant.timezone)} · created {when(tenant.created_at)} · '
        f"BAA {'signed ' + when(tenant.baa_signed_at) if tenant.baa_signed_at else 'not signed'} · id {cid}</p>"
        f'<div class="stats">{counts}</div>'
        "<h2>Features</h2><table><tr><th>Feature</th><th>State</th><th>Change</th></tr>"
        f"{feature_rows}</table>"
        '<h2>Clinic status</h2><div class="card"><p class="muted">A suspended clinic cannot sign in or accept invitations. '
        "Its data stays as it is.</p>"
        f'<form class="row" method="post" action="/clinics/{cid}/status">{hidden}<select name="status">{status_options}</select>'
        '<label><input type="checkbox" name="confirm" value="yes"> I confirm this change</label>'
        '<button class="danger">Save status</button></form></div>'
        "<h2>Staff</h2><table><tr><th>Name</th><th>Email</th><th>Role</th><th>Active</th></tr>"
        f"{staff}</table><h2>Admin actions on this clinic</h2>{actions_table(detail['audit'], show_clinic=False)}"
    )
    return layout(tenant.name, body, token=token, **notice)


def actions_table(entries: list[dict], *, show_clinic: bool = True) -> str:
    rows = (
        "".join(
            f"<tr><td>{when(e['entry'].occurred_at)}</td>"
            f"{'<td>' + esc(e['clinic']) + '</td>' if show_clinic else ''}"
            f"<td>{esc(e['entry'].action)}</td><td>{esc(e['entry'].actor_id or '')}</td>"
            f"<td class='muted'>{esc(', '.join(f'{k}: {v}' for k, v in (e['entry'].details or {}).items() if v is not None))}</td></tr>"
            for e in entries
        )
        or '<tr><td colspan="5" class="muted">Nothing yet.</td></tr>'
    )
    clinic = "<th>Clinic</th>" if show_clinic else ""
    return f"<table><tr><th>When</th>{clinic}<th>Action</th><th>By</th><th>Details</th></tr>{rows}</table>"


def audit_page(entries: list[dict], *, token: str) -> str:
    return layout("Admin log", f"<h1>Admin log</h1>{actions_table(entries)}", token=token)


def not_found_page(*, token: str | None) -> str:
    return layout("Not found", '<h1>Not found</h1><p><a href="/">Back to clinics</a></p>', token=token)
