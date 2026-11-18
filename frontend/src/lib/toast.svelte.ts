export type ToastKind = 'success' | 'error' | 'info';
export interface Toast { id: number; kind: ToastKind; message: string }

class Toasts {
  items = $state<Toast[]>([]);
  private next = 1;
  show(message: string, kind: ToastKind = 'info', ms = kind === 'error' ? 7000 : 4000) {
    const id = this.next++;
    this.items = [...this.items, { id, kind, message }];
    setTimeout(() => this.dismiss(id), ms);
  }
  success(message: string) { this.show(message, 'success'); }
  error(message: string) { this.show(message, 'error'); }
  dismiss(id: number) { this.items = this.items.filter((item) => item.id !== id); }
}
export const toast = new Toasts();
