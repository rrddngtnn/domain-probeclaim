# checkdomain.de driver research

## Live account
- customer ID: RG289071
- login: rodogini@gmail.com (password not stored here — user has it)
- 2FA code used 2026-11-16: 598549 (single-use, consumed)

## Login flow (verified live)
1. GET /login/ → `__csrf_token` in form + cookie `stid` (Varnish front)
2. POST login (Loginname + Passwort + __csrf_token) → accepted, NO captcha on login
3. → Zwei-Faktor-Authentifizierung page: 6-digit code emailed to account address
4. POST code → session as logged-in user

## Capabilities implications for driver
- gate: "email" (2FA per login!) — EmailGate + ImapCatchall is the automation path
- payment: to verify in-account (SEPA/card/voucher options)
- captcha: none on login; check order flow later
- locale: de recommended

## TODO (upgrade path — noted by user 2026-11-16)
- [ ] map in-account domain order flow (HAR) → write drivers/checkdomain.py
- [ ] ImapCatchall wiring for Gmail or catch-all domain for auto 2FA
- [ ] verify payment methods available on this account
- [ ] probe.schema against order endpoints
