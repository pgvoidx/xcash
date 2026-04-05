export const CARD_BASE = "rounded-xl border border-slate-200 bg-white shadow-sm overflow-hidden"
export const CARD_HEADER_BASE = "px-6 py-5 border-b border-slate-200 flex items-start gap-3"
export const CARD_CONTENT_BASE = "px-6 py-5"

export const buildCardClasses = (extra = {}) => {
  const { card = "", header = "", content = "" } = extra
  return {
    card: `${CARD_BASE} ${card}`.trim(),
    header: `${CARD_HEADER_BASE} ${header}`.trim(),
    content: `${CARD_CONTENT_BASE} ${content}`.trim(),
  }
}
