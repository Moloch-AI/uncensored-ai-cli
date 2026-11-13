# Security policy

## Reporting a vulnerability in this CLI

Report vulnerabilities in this repository privately through GitHub: open the repository's
**Security** tab and choose **Report a vulnerability**. Please include the CLI version
(`molochai --version`), your operating system, a description of the problem and, if you can,
steps to reproduce. Do not open a public issue for a security problem.

Examples of what belongs here: the API key reaching output, logs or files it should not, config
file permissions that are wider than documented, or model output that can control the terminal.

## Problems with the hosted API

Problems with the hosted MolochAI API or your account are not handled here. Contact MolochAI at
[molochai.dev/contact](https://molochai.dev/contact?utm_source=github&utm_medium=oss&utm_campaign=uncensored-ai-cli).

## API keys

Never post an API key in an issue, pull request, discussion, log or chat transcript. If a key has
been exposed, revoke it and create a new one at
[dash.molochai.dev/account](https://dash.molochai.dev/account?utm_source=github&utm_medium=oss&utm_campaign=uncensored-ai-cli),
then save the new one with `molochai config set-key`. Keys are not scoped (a key can read account
details and create invoices), so treat every key as fully privileged.

## Supported versions

Security fixes go into the latest release.
