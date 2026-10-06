# Contributing to Glover-R

Thanks for helping with Glover-R! Please keep changes focused and explain what
they fix, how you tested them and anything that still needs checking.

## Where to make changes

Use the maintained source and the patch pipeline. Host changes live in
`native/`, the checked adapters are in `scripts/glover/`, and ROM-verified
hooks are in `runtime-recomp/glover.us.recomp-policy.json`.

Please don't edit dependency checkouts such as RT64, N64Recomp or
N64ModernRuntime. Don't edit `RecompiledFuncs`, `RecompiledPatches` or generated
RSP output. Let the normal pipeline regenerate those files.

Keep original-instruction checks and source guards in place. If a check fails,
find out why rather than removing it or forcing the build to succeed.

## Testing

Run the Python checks from the main project folder:

```sh
python -B -m unittest discover -s tests
```

For an intentional source change, update the manifest and check it:

```sh
python -B scripts/self_check.py --write-manifest
python -B scripts/self_check.py
```

A game change also needs the normal native build and a gameplay check.
**Always produce Windows and Linux AppImage builds together.** A unit test
pass isn't a substitute for checking the game.

Describe the platform, settings and mod profile you used. If you only checked
one platform in gameplay, say so. Leave ROMs, saves, keys, generated game code
and personal settings out of commits and reports.

## Documentation

Keep the wording direct and easy to follow. The main README is for getting
people playing; put longer implementation details in the development docs.
Use British spelling, keep file paths relative and preserve third-party
credits and licence notices.

Keep maintained source, build scripts, tests, guides and approved artwork in
the public repo. The [development guide](docs/DEVELOPMENT.md) covers the builder
and patch pipeline.
