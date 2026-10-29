<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Security policy

## Scope and support

Please report suspected vulnerabilities in this fork's firmware, update handling,
browser emulator, or build and release tooling. For the web editor and installer,
use the [Felucca-WebApp repository](https://github.com/kmplngj/Felucca-WebApp).

Security fixes focus on the current `main` branch and latest release of this fork.
Older releases and experimental builds do not have a separate security maintenance
commitment; a fix may require upgrading. This personal fork is maintained as time
allows, with no guaranteed response or fix schedule.

## Reporting a vulnerability

Check this repository's [Security page](https://github.com/kmplngj/Felucca/security).
If **Report a vulnerability** is available, use it to send a private report.

If private reporting is unavailable, open an
[issue](https://github.com/kmplngj/Felucca/issues/new/choose) titled
**Private security contact requested**. Include no vulnerability details, exploit
code, logs, or personal information. Wait for the maintainer to arrange a private
channel before sharing the report. Do not put sensitive details in a public issue
or pull request.

Once a private channel is available, include the affected repository and commit or
release, build profile, relevant device/OS/browser details, reproduction steps,
expected and observed behavior, and the potential security impact. Remove secrets
and personal information from any supporting files. Coordinate disclosure with
the maintainer so there is an opportunity to investigate and prepare a fix.

Ordinary crashes, audio glitches, and feature requests without a suspected security
impact follow the [contributing guidelines](CONTRIBUTING.md#issue-notes).
