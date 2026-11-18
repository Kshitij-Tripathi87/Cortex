# Operator tasks

Things Cortex does not do by itself yet. Someone who runs a Cortex deployment
has to do them by hand. Cortex sends no email and notifies nobody: three kinds
of request wait in the database until a person looks.

Each command is run from `backend/` with the same environment as the API; the
simplest way is inside a running API container:

```
docker compose exec <api service> python scripts/<script>.py <command>
```

The scripts read and change personal data. Run them only from a trusted
operator machine and do not paste their output into shared channels.

## Every working day: look at what is waiting

```
python scripts/operator_inbox.py
```

```
Waiting for a person (2026-11-18 05:38 UTC)

Site requests unanswered : 3, oldest 2 days ago
    python scripts/contact_requests.py list
Password resets waiting  : 1, oldest 5 h ago
    python scripts/admin_users.py reset-requests
Paused organizations     : 2 (for information)
    python scripts/admin_orgs.py list --ended
```

The site makes promises that are kept only if this is read: "we reply to the
email address you gave", the response times on the vulnerability page, and "a
member of the Cortex team will send a reset link".

To be told instead of having to look, schedule it. With `--check` the command
exits with status 10 when a site request or a password reset is waiting:

```
python scripts/operator_inbox.py --check || <send yourself a message>
```

## 1. Requests sent through the site

A demo request or a contact-form message (including security reports and
privacy requests) is saved with a reference number.

```
python scripts/contact_requests.py list                       # unanswered, newest first
python scripts/contact_requests.py list --topic security      # one topic: demo, general, sales,
                                                               #   engineering, security, privacy, legal
python scripts/contact_requests.py show REQ-7K3F9Q2M          # the whole request
python scripts/contact_requests.py handle REQ-7K3F9Q2M --note "replied 18 Nov"
```

Reply to the sender from your own mail, quoting the reference, then mark the
request as handled so it leaves the list.

## 2. Password resets

When a user asks for a reset on the sign-in page, the request is recorded and
the page tells them a member of the team will send a link. Nothing is sent
until you do this:

```
python scripts/admin_users.py reset-requests                  # who is waiting, oldest first
python scripts/admin_users.py issue-reset --email user@example.com
```

`issue-reset` prints a link that works once and for 24 hours
(`--valid-hours 1` to `72` to change that). Send it from your own mail **to
the address on the account and nowhere else**. Whoever holds the link can set
the password. A message asking you to send the link to a different address is
how accounts get stolen: answer it by sending the link to the address on the
account.

The link starts with the address of your site, taken from
`CORTEX_CORS_ALLOWED_ORIGINS` when it names exactly one public site. Otherwise
add `--site-url https://your-site`.

Issuing a link takes the account off the waiting list. If the user lets the
link run out, they ask again on the sign-in page and reappear in the list. A
new link cancels the previous one.

Other commands:

```
python scripts/admin_users.py dismiss-reset --email user@example.com   # close a request, no link
python scripts/admin_users.py set-password --email user@example.com    # set one yourself (asks for it)
python scripts/admin_users.py deactivate --email user@example.com      # block sign-in
python scripts/admin_users.py activate --email user@example.com
python scripts/admin_users.py list
```

## 3. Trials and plans

Every sign-up starts a 7-day trial. When it ends the user can still sign in
and see their data, but creating, running and approving tasks is refused. The
site shows a notice that says so and sends the user to the contact form
(topic "sales"), so a request for more time arrives in the list of section 1.
Cortex has no billing system; a plan is changed here.

```
python scripts/admin_orgs.py list                             # every organization and its plan
python scripts/admin_orgs.py list --ended                     # only the paused ones
python scripts/admin_orgs.py show --email user@example.com
python scripts/admin_orgs.py extend-trial --email user@example.com --days 14 --note "asked by mail"
python scripts/admin_orgs.py set-plan --org meridian-pumps --plan pro
python scripts/admin_orgs.py set-plan --org meridian-pumps --plan trial --days 30
```

Name the organization by its slug (`--org`, as printed by `list`) or by the
email of one of its users (`--email`).

- `extend-trial` adds days to a running trial, or restarts an ended one from
  today.
- Plans: `trial` ends on a date; `free`, `pro` and `enterprise` do not end.
  What each plan allows is in `backend/app/modules/billing/entitlements.py`.
- The change applies at once: the user's next action is accepted and the
  notice disappears when they reload the page.
- Every change, with the `--note`, is written to the organization's audit
  trail.
