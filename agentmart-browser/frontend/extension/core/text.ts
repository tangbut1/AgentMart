/** 字符串工具。

 * 只有一个函数，但它是必须的：JS 的 slice/substring 按 UTF-16 **码元**计数，
 * Python 的 str[:n] 按**码点**计数。页面文案里出现 emoji 这类非 BMP 字符
 * 并不罕见，用 slice 截断会和后端差一个位置，展示出来的字段就缺字。
 */

/** 按字符（码点）截断，与 Python 的 str[:max] 语义一致。 */
export function truncate(text: string | null | undefined, max: number): string {
  const value = text ?? "";
  const chars = Array.from(value);
  if (chars.length <= max) return value;
  return chars.slice(0, max).join("");
}
