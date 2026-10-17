// 下拉選單放哪裡：預設在按鈕下面；下面放不下就翻到上面（10/15 最下面那一頁點「⋯」選單超出頁面）；
// 上下都放不下就貼齊視窗底部（選單本身最高 70vh，裡面可以捲）。rect＝按鈕的位置，view＝視窗大小。
export function menuPosition(rect, width, height, view) {
  if (!rect) return undefined;
  const left = Math.max(8, Math.min(rect.left, view.width - width - 8));
  const below = rect.bottom + 6;
  if (!height || below + height <= view.height - 8) return { top: below, left };
  const above = rect.top - 6 - height;
  if (above >= 8) return { top: above, left };
  return { top: Math.max(8, view.height - height - 8), left };
}
