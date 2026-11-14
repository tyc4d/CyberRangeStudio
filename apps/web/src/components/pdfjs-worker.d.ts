// Vite `?url` import of the pdf.js worker: resolves to the URL of the bundled worker asset.
declare module "pdfjs-dist/build/pdf.worker.min.mjs?url" {
  const url: string;
  export default url;
}
