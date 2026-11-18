# Operator tasks

Things Cortex does not do by itself yet. Someone who runs a Cortex deployment
has to do them by hand. Each command is run from `backend/` with the same
environment as the API; the simplest way is inside a running API container:

```
docker compose exec <api service> python scripts/<script>.py <command>
```

The scripts read and change personal data. Run them only from a trusted
operator machine and do not paste their output into shared channels.

## 1. Read the requests sent through the site (check every working day)

The site has no mailbox behind it. A demo request or a contact-form message
(including security reports and privacy requests) is saved in the database
with a reference number. **Nothing notifies you when one arrives.**

```
python scripts/contact_requests.py list                       # unanswered, newest first
python scripts/contact_requests.py list --topic security      # one topic: demo, general, sales,
                                                               #   engineering, security, privacy, legal
python scripts/contact_requests.py show REQ-7K3F9Q2M          # the whole request
python scripts/contact_requests.py handle REQ-7K3F9Q2M --note "replied 18 Nov"
```

Reply to the sender from your own mail, quoting the reference, then mark the
request as handled so it leaves the list. The site tells visitors "we reply to
the email address you gave", and the vulnerability page states response times:
those promises are kept only if this list is read.
