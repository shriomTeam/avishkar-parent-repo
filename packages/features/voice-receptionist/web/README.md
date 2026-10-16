# Voice receptionist frontend

This folder owns voice pages/layout, components, types, demo state, adapters, styles and browser tests. `apps/web/app/(fullscreen)/voice-receptionist` contains thin exports only. Branding is shared under `/brand`; there are currently no feature-only static assets.

Import platform session/auth APIs from `@clinic/core/web/auth/*`, platform API/entitlement helpers from `@clinic/core/web/api`, and shared controls from `@clinic/ui`. Never import `apps/web`, its `@/` alias or another feature. Local implementation imports are relative.

The feature workspace declares `clinic.webTests` for automatic browser-test discovery. Its Python entitlement tests live in `../tests`. The UI continues to use explicit demo data; live voice API implementation is separate work.

The removal acceptance check is `python scripts/check_voice_removal.py` from the repo root with all DATABASE_* and TEST_* URLs pointing to a disposable migrated database. CI runs this after the normal browser suite. It removes this entire feature, its route folder and dependency/architecture registrations from an isolated copy, then verifies the remaining platform build/tests/boundaries/typechecks and authentication journey. Shared DB migrations stay intact.
