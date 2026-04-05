import BrandHeading from "@/components/BrandHeading"
import LogoMark from "@/components/LogoMark"
import { useI18n } from "@/hooks/useI18n"

/**
 * 页面布局组件
 * 提供统一的页面结构、品牌标识和底部信息
 */
function PageLayout({ children, showHeader = true }) {
  const { t } = useI18n()

  return (
    <div className="min-h-svh bg-[#060B14] relative overflow-hidden">
      {/* Ambient background glows */}
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        <div className="absolute -top-64 -right-64 w-[600px] h-[600px] bg-blue-600/10 rounded-full blur-[120px]" />
        <div className="absolute -bottom-64 -left-64 w-[600px] h-[600px] bg-orange-500/[0.07] rounded-full blur-[120px]" />
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[900px] h-[500px] bg-indigo-900/[0.04] rounded-full blur-[80px]" />
      </div>

      {/* Subtle dot-grid overlay */}
      <div
        className="absolute inset-0 pointer-events-none opacity-40"
        style={{
          backgroundImage:
            "radial-gradient(circle, rgba(255,255,255,0.035) 1px, transparent 1px)",
          backgroundSize: "32px 32px",
        }}
      />

      <div className="relative z-10 max-w-4xl mx-auto p-4 pb-24">
        {showHeader && (
          <div className="text-center mb-10 mt-8">
            <div className="flex items-center justify-center mb-3">
              <BrandHeading size={44} />
            </div>
            <p className="text-sm text-slate-600">{t("common.tagline")}</p>
          </div>
        )}

        {children}
      </div>

      {/* Fixed glassmorphic footer */}
      <div className="fixed bottom-0 left-0 right-0 bg-[#060B14]/90 backdrop-blur-xl border-t border-white/[0.05]">
        <div className="max-w-4xl mx-auto py-3.5 px-4">
          <div className="flex items-center justify-center">
            <div className="flex items-center space-x-2.5">
              <span className="text-xs text-slate-700">Powered by</span>
              <div className="flex items-center space-x-1.5">
                <LogoMark size={14} className="shrink-0 opacity-50" />
                <a
                  className="font-semibold text-slate-500 text-sm hover:text-orange-400 transition-colors duration-200"
                  href="https://xca.sh"
                >
                  Xcash
                </a>
              </div>
              <span className="text-slate-800 text-xs">•</span>
              <span className="text-xs text-slate-700">Secure Crypto Payments</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

export default PageLayout
