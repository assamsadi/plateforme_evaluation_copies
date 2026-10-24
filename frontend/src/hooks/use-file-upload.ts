"use client";

import {
  type ChangeEvent,
  type DragEvent,
  type InputHTMLAttributes,
  useCallback,
  useRef,
  useState,
} from "react";

export type FileMetadata = {
  name: string;
  size: number;
  type: string;
  url: string;
  id: string;
};

export type FileWithPreview = {
  file: File | FileMetadata;
  id: string;
  preview?: string;
};

type FileUploadOptions = {
  maxFiles?: number;
  maxSize?: number;
  accept?: string;
  multiple?: boolean;
  initialFiles?: FileMetadata[];
  onFilesChange?: (files: FileWithPreview[]) => void;
  onFilesAdded?: (addedFiles: FileWithPreview[]) => void;
};

type FileUploadState = {
  files: FileWithPreview[];
  isDragging: boolean;
  errors: string[];
};

type FileUploadActions = {
  addFiles: (files: FileList | File[]) => void;
  removeFile: (id: string) => void;
  clearFiles: () => void;
  clearErrors: () => void;
  handleDragEnter: (event: DragEvent<HTMLElement>) => void;
  handleDragLeave: (event: DragEvent<HTMLElement>) => void;
  handleDragOver: (event: DragEvent<HTMLElement>) => void;
  handleDrop: (event: DragEvent<HTMLElement>) => void;
  handleFileChange: (event: ChangeEvent<HTMLInputElement>) => void;
  openFileDialog: () => void;
  getInputProps: (
    props?: InputHTMLAttributes<HTMLInputElement>,
  ) => InputHTMLAttributes<HTMLInputElement> & { ref: React.Ref<HTMLInputElement> };
};

function generateId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

export function formatBytes(bytes: number, decimals = 2): string {
  if (bytes === 0) return "0 Bytes";
  const k = 1024;
  const dm = decimals < 0 ? 0 : decimals;
  const sizes = ["Bytes", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${Number.parseFloat((bytes / k ** i).toFixed(dm))} ${sizes[i]}`;
}

// Simple wildcard/mime matching ("image/*", "application/pdf", ".pdf") —
// suffisant pour un accept de type "image/*,application/pdf,.pdf", jamais
// un vrai parseur MIME complet (hors périmètre d'un hook front-end).
function isFileTypeAccepted(file: File, accept: string): boolean {
  if (!accept || accept === "*") return true;
  const patterns = accept.split(",").map((pattern) => pattern.trim());
  return patterns.some((pattern) => {
    if (pattern.startsWith(".")) return file.name.toLowerCase().endsWith(pattern.toLowerCase());
    if (pattern.endsWith("/*")) return file.type.startsWith(pattern.slice(0, -1));
    return file.type === pattern;
  });
}

export function useFileUpload(
  options: FileUploadOptions = {},
): [FileUploadState, FileUploadActions] {
  const {
    maxFiles = Number.POSITIVE_INFINITY,
    maxSize = Number.POSITIVE_INFINITY,
    accept = "*",
    multiple = false,
    initialFiles = [],
    onFilesChange,
    onFilesAdded,
  } = options;

  const [files, setFiles] = useState<FileWithPreview[]>(() =>
    initialFiles.map((meta) => ({ file: meta, id: meta.id, preview: meta.url })),
  );
  const [isDragging, setIsDragging] = useState(false);
  const [errors, setErrors] = useState<string[]>([]);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const emitChange = useCallback(
    (next: FileWithPreview[]) => {
      setFiles(next);
      onFilesChange?.(next);
    },
    [onFilesChange],
  );

  const addFiles = useCallback(
    (incoming: FileList | File[]) => {
      const incomingArray = Array.from(incoming);
      const nextErrors: string[] = [];

      const existingSignatures = new Set(
        files.map((f) => (f.file instanceof File ? `${f.file.name}-${f.file.size}` : `${f.file.name}-${f.file.size}`)),
      );

      const accepted: FileWithPreview[] = [];
      for (const file of incomingArray) {
        if (!isFileTypeAccepted(file, accept)) {
          nextErrors.push(`"${file.name}" n'est pas un type de fichier accepté.`);
          continue;
        }
        if (file.size > maxSize) {
          nextErrors.push(`"${file.name}" dépasse la taille maximale (${formatBytes(maxSize)}).`);
          continue;
        }
        const signature = `${file.name}-${file.size}`;
        if (existingSignatures.has(signature)) {
          nextErrors.push(`"${file.name}" a déjà été ajouté.`);
          continue;
        }
        existingSignatures.add(signature);
        accepted.push({
          file,
          id: generateId(),
          preview: file.type.startsWith("image/") ? URL.createObjectURL(file) : undefined,
        });
      }

      if (accepted.length === 0) {
        setErrors(nextErrors);
        return;
      }

      const base = multiple ? files : [];
      let merged = [...base, ...accepted];
      if (multiple && Number.isFinite(maxFiles) && merged.length > maxFiles) {
        nextErrors.push(`Vous ne pouvez pas ajouter plus de ${maxFiles} fichier(s).`);
        merged = merged.slice(0, maxFiles);
      }

      setErrors(nextErrors);
      emitChange(merged);
      onFilesAdded?.(accepted);
    },
    [accept, emitChange, files, maxFiles, maxSize, multiple, onFilesAdded],
  );

  const removeFile = useCallback(
    (id: string) => {
      const target = files.find((f) => f.id === id);
      if (target?.preview && target.file instanceof File) URL.revokeObjectURL(target.preview);
      emitChange(files.filter((f) => f.id !== id));
    },
    [emitChange, files],
  );

  const clearFiles = useCallback(() => {
    for (const f of files) {
      if (f.preview && f.file instanceof File) URL.revokeObjectURL(f.preview);
    }
    emitChange([]);
    if (inputRef.current) inputRef.current.value = "";
  }, [emitChange, files]);

  const clearErrors = useCallback(() => setErrors([]), []);

  const handleDragEnter = useCallback((event: DragEvent<HTMLElement>) => {
    event.preventDefault();
    event.stopPropagation();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback((event: DragEvent<HTMLElement>) => {
    event.preventDefault();
    event.stopPropagation();
    setIsDragging(false);
  }, []);

  const handleDragOver = useCallback((event: DragEvent<HTMLElement>) => {
    event.preventDefault();
    event.stopPropagation();
  }, []);

  const handleDrop = useCallback(
    (event: DragEvent<HTMLElement>) => {
      event.preventDefault();
      event.stopPropagation();
      setIsDragging(false);
      if (event.dataTransfer.files?.length) {
        addFiles(multiple ? event.dataTransfer.files : [event.dataTransfer.files[0]]);
      }
    },
    [addFiles, multiple],
  );

  const handleFileChange = useCallback(
    (event: ChangeEvent<HTMLInputElement>) => {
      if (event.target.files?.length) addFiles(event.target.files);
    },
    [addFiles],
  );

  const openFileDialog = useCallback(() => {
    inputRef.current?.click();
  }, []);

  const getInputProps = useCallback(
    (props: InputHTMLAttributes<HTMLInputElement> = {}) => ({
      ...props,
      type: "file" as const,
      accept: props.accept ?? accept,
      multiple: props.multiple ?? multiple,
      onChange: handleFileChange,
      ref: inputRef,
    }),
    [accept, handleFileChange, multiple],
  );

  return [
    { files, isDragging, errors },
    {
      addFiles,
      removeFile,
      clearFiles,
      clearErrors,
      handleDragEnter,
      handleDragLeave,
      handleDragOver,
      handleDrop,
      handleFileChange,
      openFileDialog,
      getInputProps,
    },
  ];
}
