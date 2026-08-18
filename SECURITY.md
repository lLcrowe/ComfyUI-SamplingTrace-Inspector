# Security Policy

## Supported version

Security fixes target the latest public preview on the default branch.

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability or include private workflows, prompts, model filenames, generated images, or run folders in a report.

Use GitHub's **Security → Report a vulnerability** form for this repository. Include only the minimum reproduction steps, affected version, expected impact, and any safe diagnostic output. If private vulnerability reporting is unavailable, contact the maintainer through the private contact method shown on the GitHub profile before sharing details.

## Deployment boundary

The plugin shares ComfyUI's server access boundary. Do not expose ComfyUI directly to the public internet. When remote access is required, place authentication and appropriate network controls in front of ComfyUI.
