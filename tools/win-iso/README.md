# Windows installation media catalog and downloader

This is a standalone media acquisition helper. It does not change the B4 catalogue, IR schema, deployment backend, or validate a Windows VM. The default destination is `/home/tyc4d/cr-images`; the downloader creates it as needed.

## Contents

- `catalog.json`: known official source pages, release/edition/language/architecture notes, source type, and licensing caveats.
- `downloader.py`: catalog listing plus resumable download from a Microsoft-issued HTTPS URL, progress, SHA-256 calculation, optional comparison with Microsoft's published digest, and a `.part` file retained on interrupted or failed downloads.

Example:

```sh
python3 tools/win-iso/downloader.py list
python3 tools/win-iso/downloader.py download windows-server-2022-eval \
  --url 'https://download.microsoft.com/.../temporary-server-iso.iso' \
  --sha256 '<64-hex-digits-copied-from-Microsoft>'
```

Microsoft download links may be signed and expire. Open the catalog's `source_page`, complete Microsoft's own selection/registration flow, and pass the resulting ISO URL. The downloader only accepts HTTPS links whose host is `microsoft.com` or a subdomain, or `windows.com` or a subdomain. It checks redirects too. It does not accept arbitrary CDNs; if Microsoft changes to a different official host, update the explicit host allowlist after verifying Microsoft's documentation. Do not paste credentials or tokens into logs.

The tool resumes a `.part` file with HTTP Range where supported. If the server does not honor Range, it restarts the partial file. Once complete it calculates SHA-256. If `--sha256` is supplied, mismatch prevents promotion to `.iso`. Without Microsoft's expected digest, the resulting hash identifies the bytes downloaded but does **not** establish authenticity independently. A 5–7 GB download is expected for contemporary client media; the exact size varies by release, language and architecture. Server ISO size also varies; use Microsoft's displayed size/Content-Length rather than a fixed estimate. This task did not download an ISO.

## Retrieval research and boundaries

### Microsoft consumer download / MCT

Microsoft's Windows 10/11 software download pages offer consumer media. The browser flow selects product/language/architecture and issues direct, time-limited download URLs; recent Windows 11 page also publishes per-language SHA-256 values. Microsoft's page documents calculating SHA-256 with `Get-FileHash` and comparing with its table. The endpoint family behind that UI includes `GetSkuInformationByProductEdition` and `GetProductDownloadLinksBySku` (page IDs, SKU IDs, session IDs, locale, and request shape are implementation details, not a stable public API contract). A caller should resolve through the actual Microsoft page rather than assume a permanent direct URL.

AveYo's `MediaCreationTool.bat` is a Windows wrapper/automation around Microsoft's signed Media Creation Tool. The repository documents choosing MCT version, edition, language and architecture, then having MCT create ISO/USB media. The script's business-edition support edits/provides MCT `products.xml` metadata and the MCT then obtains ESDs from Microsoft; historical product catalogs/links can expire. Its behavior includes post-processing media in some presets, so this module does not run or copy that script. We use the general approach of selecting official Microsoft media metadata and never distribute the wrapper's patched media.

Business editions (Enterprise/Education/VL) can be delivered by Microsoft's business-media tool or subscription portals, but a public download does not grant a license. Enterprise/VL usage and activation require appropriate organizational entitlement. The current helper catalogs that source route as conditional; it will not fabricate links or keys.

### Evaluation Center / public availability

Microsoft Evaluation Center publicly offers evaluation ISOs for Windows Server releases (currently catalogued: 2025, 2022, 2019), with registration/terms depending on release and locale. Server 2022 page says its evaluation expires after 180 days and must activate online in the first 10 days to avoid automatic shutdown; it contains Standard and Datacenter evaluation indexes and Core/Desktop Experience choices. Server 2025 and 2019 pages must be checked at use time for current availability and terms. Evaluation media is for evaluation under Microsoft's terms, not a general production license.

Windows 10/11 consumer ISOs are publicly downloadable without entering a product key merely to obtain the file. Downloadability is separate from installation/activation rights. Windows 10 is out of free support since 2025-10-14. The catalog does not claim perpetual availability of old releases.

### UUP Dump

UUP Dump is a third-party catalog/API that identifies update payloads. Its own FAQ says its official API is hosted at `api.uupdump.net`, and that chosen UUP files are downloaded from Microsoft update/CDN infrastructure, then converted into an ISO by scripts. Thus individual payload origins can be Microsoft, but the selector, scripts, assembly process and resulting ISO are not Microsoft-operated or Microsoft-signed ISO delivery. It is intentionally not an allowed download source for this official-only module. Do not call UUP Dump an official Microsoft download mechanism. If used in a separate approved workflow, verify Microsoft package signatures/hashes and independently validate the assembled ISO; that still does not turn it into a Microsoft-published ISO digest.

### Sizes and integrity

- Consumer client ISO: typically around 5–7 GB, dependent on version, language and architecture; Microsoft page's download metadata is authoritative for that selection.
- Server ISO: variable, several GB; use the current Evaluation Center response/content metadata.
- Microsoft's published SHA-256 table is the preferred end-to-end comparison when available. The downloader can calculate SHA-256 for every file and compare it to an expected value supplied by the caller. It does not infer an expected digest from a URL or treat a locally computed digest as a trust anchor.
- TLS protects transport to the official endpoint. Range/ETag support is server-dependent; resume is opportunistic. No whole ISO was fetched during implementation.

## B4 `image_ref` handoff

After a human has downloaded and reviewed the file, a future B4 VM image builder can consume it as a local builder input, for example:

```yaml
runtime: vm
guest:
  os_family: windows
  os_release: windows-server-2022-eval
  image_ref: file:///home/tyc4d/cr-images/WindowsServer2022-eval.iso
  image_digest: sha256:<digest printed by downloader>
```

This is explanatory only. The B4 design calls for an approved local image or builder source; raw installation ISO is not necessarily a boot-ready VM image. A separately approved provisioning/build step must install Windows and produce a VM artifact. Keep the ISO's evaluation license/source metadata and digest with that artifact. This task intentionally does not edit `catalogue/components.json`, contracts, or the deployment pipeline.

## Sources checked (2026-11-15)

- AveYo project and README: <https://github.com/AveYo/MediaCreationTool.bat>
- Microsoft Windows 11 download and SHA-256 guidance: <https://www.microsoft.com/software-download/windows11>
- Microsoft Windows 10 download: <https://www.microsoft.com/software-download/windows10>
- Microsoft Windows Server 2025 Evaluation Center: <https://www.microsoft.com/evalcenter/evaluate-windows-server-2025>
- Microsoft Windows Server 2022 Evaluation Center: <https://www.microsoft.com/evalcenter/evaluate-windows-server-2022>
- Microsoft Windows Server 2019 Evaluation Center: <https://www.microsoft.com/evalcenter/evaluate-windows-server-2019>
- UUP Dump FAQ (third party): <https://git.uupdump.net/uup-dump/misc/src/branch/master/FAQ.md>
