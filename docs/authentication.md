# Authentication

Users register and sign in through user-only routes. Officers use a separate sign-in route and can only be created by an administrator. Both use one internal account store with Argon2id password hashes, but role and domain profile are loaded from the server on every authenticated request.

Access tokens last 15 minutes by default. Refresh tokens last 14 days, are recorded by ID, rotate on use, and are revoked on logout. The API never accepts a client-supplied role or profile ID. User report access is ownership-scoped; officer access is membership-scoped; status actions are additionally assignment-scoped. Live connections require the same short-lived access token.

Browser deployments should keep access tokens in memory where possible and use secure, same-site, HTTP-only cookies for refresh tokens through a same-origin gateway. The prototype uses local storage so the standalone PWA and API can run independently during development.

