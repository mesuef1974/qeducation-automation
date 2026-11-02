import { reactive } from "vue";

export interface ConfirmAsk {
  title: string;
  body: string;
  confirm: string;
  /** كتابة على المنصة أو حذف: زر التأكيد بلون التحذير */
  danger?: boolean;
}

// حوار تأكيد واحد في التطبيق (ConfirmDialog.vue يعرضه)
export const confirmState = reactive<{ ask: ConfirmAsk | null; resolve: ((ok: boolean) => void) | null }>({
  ask: null,
  resolve: null,
});

export function settleConfirm(ok: boolean) {
  confirmState.resolve?.(ok);
  confirmState.ask = null;
  confirmState.resolve = null;
}

export function useConfirm() {
  return (ask: ConfirmAsk) =>
    new Promise<boolean>((resolve) => {
      settleConfirm(false); // أي سؤال سابق معلّق يُعدّ رفضًا
      confirmState.ask = ask;
      confirmState.resolve = resolve;
    });
}
