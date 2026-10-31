# Security policy

## Scope

Pluto Scanner is a passive SDR receiver and analysis tool. It does not
implement jamming, spoofing, active interception or unauthorised
transmission.

## Reporting a vulnerability

Please do not open a public issue for a security-sensitive report. Use
GitHub's private vulnerability reporting or contact the maintainer privately.

Include:

- affected version/commit;
- steps to reproduce;
- expected and actual behaviour;
- whether real hardware was involved.

## Sensitive data

The following are local-only and must never be committed:

- `user_data/` (known contacts, local signatures);
- `scan_logs/` and `drone_logs/`;
- IQ evidence clips (`*.cf32`);
- screenshots with personal information;
- device serials, USB URIs, IP addresses and tokens.

The provided `.gitignore` excludes these by default. Review `git status`
before every push.

## Radio regulations

Use the software only for passive reception and in compliance with local law.
The authors are not responsible for misuse.
