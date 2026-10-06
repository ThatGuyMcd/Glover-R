# Glover-R launcher branding

The Glover-R wordmark supplied by ThatGuyMcd is used for the launcher spinner,
Windows executable icon, SDL window icon and Linux AppImage desktop icon.
The square desktop variants preserve the wordmark's proportions and use a
transparent background.

The maintained images are in `native/src/UI`. The source assembler copies them
through the patch pipeline, and Windows/Linux packaging includes the relevant
icon formats. The original game font atlas is not included.

Bungee Regular is used for headings, navigation and main actions. It is an
independently licensed font from the Bungee Project Authors, under the SIL
Open Font License 1.1. The source and full notice are available in the
[Bungee font directory](https://github.com/google/fonts/tree/main/ofl/bungee).

Reading text uses Microsoft Selawik Regular and Semibold, release 1.01,
also under the SIL Open Font License 1.1. See the
[Selawik release](https://github.com/microsoft/Selawik/releases/tag/1.01).

The unmodified fonts and original notices live in `native/src/UI/fonts`.
Packages include them under `assets/ui/fonts`, with additional licence copies
under `licenses/bungee` and `licenses/selawik`. No installed system font is
needed. Keep the original notices with every distributed copy.
