# Third-Party Notices

This project incorporates or builds on the components below. **Each retains its own license**, and
that license governs that component — it is not superseded by this repository's `LICENSE` or
`DATA-LICENSE.md` (both CC BY-NC 4.0). This file is a convenience summary; the authoritative license for any
released data file is the `license` field in its `manifest.json`.

## Software

- **ABIDES** (organizer-maintained fork) — **BSD-3-Clause**. Used by Track 3. The original ABIDES
  code remains under BSD-3-Clause and may be used commercially from upstream; **only the organizers'
  additions** (scenarios, regression harness, stylized-fact checker, throughput timer) are licensed
  under this repository's `LICENSE` (CC BY-NC 4.0).
- **Python dependencies** of `qfbench2-common` (NumPy, SciPy, jsonschema, pandas, PyArrow,
  transformers, PyTorch, and others) — each under its own license (BSD / Apache-2.0 / MIT / PSF).
  These are *installed*, not redistributed in this repository.

## Datasets & corpora

- **QF-Bench** (Track 1 practice pool) — **CC BY-NC 4.0**. Redistributed here under those terms with
  attribution. Source: https://github.com (QFBench project) / the QFBench site.
- **SEC EDGAR** (incl. EDGAR-CORPUS / EDGAR-CRAWLER), **U.S. Federal Reserve** (FRED / ALFRED,
  H.10), **U.S. BEA**, **U.S. Treasury** — works of the U.S. Government, **public domain** (no
  copyright). The organizers' *curation, selection, labels, and questions* built from them are
  CC BY-NC 4.0.
- **JKP Global Factor Data** (jkpfactors.com) — per the providers' terms (academic use).
- **Global Macro Database** (globalmacrodata.com) — per the providers' terms.
- **Open Source Bond Asset Pricing / OSBAP** (openbondassetpricing.com; Dickerson, Mueller &
  Robotti; Dickerson, Nozawa & Robotti) — per the site's terms; **pin a specific release**.
  Only openly-posted factor / ML-panel files are used; **WRDS-gated panels are not redistributed**.

## Vendor data — referenced, NOT redistributed

- **Databento** (Track 3 limit-order-book data) and **Bloomberg** — commercial vendor data under
  their respective agreements. **Not committed** to these repositories; referenced by checksum and
  access instructions only. Any derived statistics are used strictly per the vendor's terms.

---

If you believe a component is mis-attributed or a license has changed, contact the Agenthon 2026
organizers before redistributing.
