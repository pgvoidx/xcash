import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { getChainIconUrl, getChainDisplayName, isTestnet } from "@/lib/cryptoIcons"
import { useI18n } from "@/hooks/useI18n"

function ChainSelector({ availableMethods, selectedCrypto, selectedChain, onChainChange, disabled = false }) {
  const { t } = useI18n()

  if (!availableMethods || !selectedCrypto || !availableMethods[selectedCrypto]) {
    return (
      <div className="p-4 border border-dashed border-white/[0.05] rounded-xl text-center bg-white/[0.01]">
        <p className="text-sm text-slate-700">
          {!selectedCrypto ? t("selector.selectTokenFirst") : t("selector.noNetworks")}
        </p>
      </div>
    )
  }

  const chainOptions = availableMethods[selectedCrypto]

  return (
    <Select value={selectedChain} onValueChange={onChainChange} disabled={disabled}>
      <SelectTrigger className="h-12 text-left bg-white/[0.04] border-white/[0.1] text-white hover:bg-white/[0.07] focus:ring-orange-500/30 focus:border-orange-500/40 transition-colors shadow-none cursor-pointer">
        <SelectValue
          placeholder={
            <div className="flex items-center space-x-2 text-slate-500">
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1"
                />
              </svg>
              <span>{t("selector.selectNetwork")}</span>
            </div>
          }
        />
      </SelectTrigger>
      <SelectContent className="bg-[#0D1524] border-white/[0.1] shadow-2xl shadow-black/60">
        {chainOptions.map((chain) => (
          <SelectItem
            key={chain}
            value={chain}
            className="cursor-pointer text-white hover:bg-white/[0.06] focus:bg-white/[0.06] focus:text-white"
          >
            <div className="flex items-center space-x-3">
              <img
                src={getChainIconUrl(chain)}
                alt={chain}
                className="w-8 h-8 rounded-full"
                onError={(e) => {
                  e.target.style.display = "none"
                  e.target.nextElementSibling.style.display = "flex"
                }}
              />
              <div
                className="w-8 h-8 rounded-full bg-gradient-to-br from-slate-500 to-slate-700 items-center justify-center hidden"
              >
                <svg
                  className="w-4 h-4 text-white"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1"
                  />
                </svg>
              </div>
              <div>
                <p className="font-medium text-white">{getChainDisplayName(chain)}</p>
                <p className="text-xs text-slate-500">
                  {isTestnet(chain) ? t("selector.testNetwork") : t("selector.mainNetwork")}
                </p>
              </div>
            </div>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

export default ChainSelector
