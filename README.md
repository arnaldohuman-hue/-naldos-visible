# Naldo's Roller Shutter Doors, Automotive & Steel Works

Static website for this repository only: [arnaldohuman-hue/-naldos-visible](https://github.com/arnaldohuman-hue/-naldos-visible).

The page is `index.html` plus JPEG files in `images/`. Photo paths are relative (`images/...`), so they resolve under the GitHub Pages project path `/-naldos-visible/` when the site is opened with that directory’s trailing slash. Root-absolute paths such as `/images/...` are not used.

`.nojekyll` is included so Pages serves the files directly.

## Pages status

GitHub Pages is **not enabled** on this repository yet. Merging the site does not publish it until Pages is turned on for **this** repository.

After the site is on `main`, the remaining step is:

1. Open **Settings → Pages** for `arnaldohuman-hue/-naldos-visible` only.
2. Under **Build and deployment**, set **Source** to **GitHub Actions**.
3. Save. If the “Deploy static content to Pages” workflow already failed because Pages was still off, open **Actions**, select that workflow, and run it again.

Do not select **Deploy from a branch** while `.github/workflows/pages.yml` is the publisher. Do not add a custom domain.

The workflow publishes `index.html`, `.nojekyll`, and `images/` with the official `actions/configure-pages`, `actions/upload-pages-artifact`, and `actions/deploy-pages` actions. It runs on a push to `main` and can also be started manually.

Until that settings step succeeds, there is no live Pages URL.

## Local preview

From this directory:

```bash
python3 tests/test_site.py
python3 -m http.server 8080 --bind 127.0.0.1
```

Open `http://127.0.0.1:8080/` (the same files, at the server root) or serve a parent directory so the URL is `http://127.0.0.1:8080/-naldos-visible/`.

## Content on the page

Business name, manager (Rhenvin Human), phone (`079 695 1572`), and address (12 Rewlatch Road, Rewlatch 2197, Johannesburg) are the details already in the approved page. The same number is a WhatsApp contact (`https://wa.me/27796951572`). Email is not listed. Solar panel installation is a service, and the project gallery includes solar installation photos.
