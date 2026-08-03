declare module 'pdfjs-dist' {
  export interface PDFDocumentProxy {
    numPages: number;
    getPage(pageNum: number): Promise<PDFPageProxy>;
  }
  export interface PDFPageProxy {
    getViewport(params: { scale: number }): { width: number; height: number };
    render(params: { canvasContext: CanvasRenderingContext2D; viewport: any }): { promise: Promise<void> };
  }
  export interface PDFLoadingTask {
    promise: Promise<PDFDocumentProxy>;
  }
  export const GlobalWorkerOptions: { workerSrc: string };
  export const version: string;
  export function getDocument(params: { data: Uint8Array } | string): PDFLoadingTask;
}
