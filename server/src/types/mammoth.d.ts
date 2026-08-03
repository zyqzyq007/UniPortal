declare module 'mammoth' {
  export interface ExtractResult {
    value: string;
    messages: Array<{ type: string; message: string }>;
  }
  export function extractRawText(options: { buffer: Buffer }): Promise<ExtractResult>;
  export function convertToHtml(options: { buffer: Buffer }): Promise<ExtractResult>;
  const _default: { extractRawText: typeof extractRawText; convertToHtml: typeof convertToHtml };
  export default _default;
}
