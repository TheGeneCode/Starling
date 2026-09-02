# Security Policy

Starling users hold a **Google Cloud service-account JSON key** that authenticates API
calls billed to their own account, plus a `.env` file that names its path, and a usage
log that records article filenames. Treat any vulnerability that could leak, misuse, or
escalate access through that key as high priority.

## Reporting a Vulnerability

Please **do not** open a public GitHub issue for security vulnerabilities.

Instead, use GitHub's private vulnerability reporting:

1. Go to the [Security tab](https://github.com/TheGeneCode/Starling/security) of this repository.
2. Click **Report a vulnerability**.
3. Describe the issue, steps to reproduce, and potential impact.

You should get an acknowledgment within a few days. Confirmed issues will be prioritized
for a fix and you'll be credited in the release notes, unless you'd rather stay anonymous.

## Supported Versions

Only the latest released version receives security fixes. Please confirm you're on the
newest [release](https://github.com/TheGeneCode/Starling/releases) before reporting.

## If Your Service-Account Key Leaks

A leaked key lets the holder call the APIs enabled on your project and bill you for
them. If you followed the README and granted the service account **no IAM roles**, that
is the limit of the damage — but it is not nothing, and Text-to-Speech at Studio rates is
US$160 per million characters.

1. **Revoke the key first.** Google Cloud Console → **IAM & Admin → Service Accounts** →
   the account → **Keys** → delete the leaked key. Revoke before anything else; every
   later step is slower and none of them stops the key from working.
2. **Check for unexpected usage.** **Billing → Reports** filtered to Cloud Text-to-Speech,
   and **APIs & Services → Text-to-Speech API → Metrics**, for traffic you did not
   generate. If you find any, contact Google Cloud Billing Support.
3. **Issue a replacement key** and point `STARLING_GOOGLE_CREDENTIALS` at it.
4. **If it reached a git repository, rotating is mandatory and deleting the commit is not
   enough.** Anyone who cloned or forked the repository, and every cache and mirror
   including GitHub's, may still hold it. Step 1 is what makes it harmless. Rewriting
   history afterwards is housekeeping, not remediation.
5. **Consider deleting the whole service account** and creating a fresh one, if you are
   not certain which keys existed on it.
6. **Set a budget alert** on the project — **Billing → Budgets & alerts** — so unexpected
   spend is noticed within a day rather than at the end of the month.

GitHub's secret scanning detects Google service-account keys in public repositories and
notifies Google, which may disable the key automatically. **Do not rely on that** — it is
a backstop, and it does nothing for a key leaked anywhere other than a public GitHub
repository.

## Reducing the Blast Radius

- Grant the service account **no IAM roles**.
- Enable only the Text-to-Speech API on the project.
- Keep the key outside every git working tree.
- Cap the API's requests-per-minute quota if you want a hard ceiling on spend.
- Use a project dedicated to Starling rather than one that also holds other data.
