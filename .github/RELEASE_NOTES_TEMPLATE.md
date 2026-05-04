<!--
  Release-notes stencil for atrium.

  NOT a GitHub-native template (releases have no equivalent of
  PULL_REQUEST_TEMPLATE.md). It's a stencil this repo's
  ``scripts/release-notes.sh`` substitutes against — placeholders
  surrounded by double-curlies are filled in, and one ``## <title> —
  closes #N`` section is pre-stubbed for every ``closes #N`` referenced
  in commits since the previous tag. The maintainer then writes the
  per-issue prose by hand.

  Placeholders the script knows about:
    {{VERSION}}      0.16.0
    {{MINOR}}        0.16
    {{MAJOR}}        0
    {{PREV_VERSION}} 0.15.3       (highest existing v* tag at run time)
    {{PREV_MINOR}}   0.15

  Maintainer flow per RELEASING.md step 9:
    1. ``make release-notes V=0.16.0``
    2. open ``.context/release-notes-v0.16.0.md``
    3. write the Highlights paragraph + the per-issue prose
    4. delete sections that don't apply (e.g. Documentation if nothing
       in docs/ moved this release)
    5. ``gh release create v0.16.0 --notes-file .context/release-notes-v0.16.0.md``
-->

## Highlights

<!--
  1-paragraph summary aimed at non-engineers reading the GitHub release
  email. What shipped. What's the motivation. What's NOT in scope.
  Mention if there are no migrations / no breaking changes / no env
  additions — the absence of upgrade pain is itself the headline.

  Image and host SDK packages bumped to {{VERSION}} in lockstep.
-->

<!-- {{ISSUE_SECTIONS}} -->

## Host bundle impact

<!--
  1-3 sentences for host-bundle authors. Name every registry hook,
  SDK export, config namespace, or env var that moved this release,
  and link the v{{VERSION}} row in ``docs/compat-matrix.md``.
  Pin recommendation: ``@brendanbank/atrium-host-{types,bundle-utils,test-utils}@^{{VERSION}}``.

  Write **"No host-facing changes."** verbatim when nothing on the
  host extension contract moved — that absence is the answer host
  authors are scanning for.
-->

## Documentation

<!--
  What changed in ``docs/``. Even a one-liner. Hosts read this to know
  whether to re-skim the contract docs. Delete this section if nothing
  in docs/ moved.

  - ``docs/compat-matrix.md`` — new v{{VERSION}} row.
  - ``docs/published-images.md`` — …
  - ``RELEASING.md`` — …
-->

## Image details

The image is published on `v*` git tag push. The `v{{VERSION}}` tag
produces these registry tags on `ghcr.io/brendanbank/atrium`:

| Tag         | Use it when                                                |
| ----------- | ---------------------------------------------------------- |
| `{{VERSION}}` | Full pin — fully deterministic deploys.                  |
| `{{MINOR}}` | Auto-uptake patch releases. Recommended for prod.          |
| `{{MAJOR}}` | Auto-uptake minor releases. Useful in lower environments.  |
| `latest`    | Tinkering only.                                            |

`linux/amd64` and `linux/arm64`. Public — no auth required to pull.

The host SDK packages publish to `https://registry.npmjs.org/` under
the `@brendanbank` scope, also public. v{{VERSION}} publishes
`@brendanbank/atrium-host-types@{{VERSION}}`,
`@brendanbank/atrium-host-bundle-utils@{{VERSION}}`,
`@brendanbank/atrium-test-utils@{{VERSION}}`, and
`@brendanbank/create-atrium-host@{{VERSION}}`, each with a signed
provenance attestation.

## Upgrading from v{{PREV_VERSION}}

**1. compose.yaml** — bump the image:

```yaml
# auto-uptake patch releases
services:
  api:
    image: ghcr.io/brendanbank/atrium:{{MINOR}}

# or fully pinned
services:
  api:
    image: ghcr.io/brendanbank/atrium:{{VERSION}}
```

**2. frontend/package.json** — bump the host SDK packages if you've adopted any of them:

```json
{
  "dependencies": {
    "@brendanbank/atrium-host-types": "^{{VERSION}}",
    "@brendanbank/atrium-host-bundle-utils": "^{{VERSION}}",
    "@brendanbank/atrium-test-utils": "^{{VERSION}}"
  }
}
```

`pnpm install`, rebuild the host bundle, redeploy.

<!--
  If the alembic head moved, add a ``**3. Run the migration**`` block
  here naming the new revision and what it does. The standard atrium
  worker container runs ``alembic upgrade head`` on boot so this is
  automatic; out-of-band runners need to add it to their pipeline.
  Delete this paragraph if the head didn't move.
-->

<!--
  If env vars changed, add a ``**4. Set the new env var**`` block.
  Delete if not applicable.
-->

No breaking API changes. Existing hosts that don't use the new
fields, endpoints, or hooks keep working untouched.
