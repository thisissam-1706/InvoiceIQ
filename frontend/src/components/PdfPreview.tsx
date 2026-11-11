export default function PdfPreview({ url, fileName }: { url: string; fileName: string }) {
  return (
    <div className="overflow-hidden rounded-b-xl bg-slate-100">
      <object data={`${url}#toolbar=0&navpanes=0&view=FitH`} type="application/pdf" className="h-[520px] w-full" aria-label={fileName}>
        <div className="flex h-[520px] flex-col items-center justify-center gap-2 text-sm text-slate-500">
          <span>The browser cannot display this PDF inline.</span>
          <a href={url} target="_blank" rel="noreferrer" className="font-medium text-indigo-600 hover:underline">
            Open {fileName}
          </a>
        </div>
      </object>
    </div>
  );
}
