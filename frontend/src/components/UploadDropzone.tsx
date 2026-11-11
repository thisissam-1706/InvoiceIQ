import { DragEvent, useRef, useState } from "react";
import { Spinner, UploadIcon } from "./Icons";

export default function UploadDropzone({ onFiles, busy }: { onFiles: (files: File[]) => void; busy: boolean }) {
  const [over, setOver] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  const accept = (list: FileList | null) => {
    const files = Array.from(list ?? []);
    if (files.length) onFiles(files);
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setOver(false);
    accept(e.dataTransfer.files);
  };

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={onDrop}
      onClick={() => !busy && input.current?.click()}
      className={`flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-10 text-center transition-colors ${
        over ? "border-indigo-500 bg-indigo-50" : "border-slate-300 bg-white hover:border-indigo-400 hover:bg-slate-50"
      }`}
    >
      <input ref={input} type="file" accept="application/pdf,.pdf" multiple className="hidden" onChange={(e) => accept(e.target.files)} />
      <div className="flex h-11 w-11 items-center justify-center rounded-full bg-indigo-50 text-indigo-600">
        {busy ? <Spinner className="h-5 w-5" /> : <UploadIcon className="h-5 w-5" />}
      </div>
      <div className="mt-3 text-sm font-medium text-slate-900">{busy ? "Uploading…" : "Drop invoice PDFs here, or click to browse"}</div>
      <div className="mt-1 text-xs text-slate-500">Digital or scanned PDFs, up to 25 MB each. One file opens its live run; several go to the dashboard.</div>
    </div>
  );
}
