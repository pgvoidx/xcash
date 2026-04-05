import BrandHeading from "@/components/BrandHeading"
import { useI18n } from "@/hooks/useI18n"

function LoadingState() {
  const { t } = useI18n()

  return (
    <div className="min-h-svh bg-[var(--app-bg)] flex flex-col items-center justify-center"
      style={{
        backgroundImage: "radial-gradient(circle, rgba(255,255,255,0.035) 1px, transparent 1px)",
        backgroundSize: "32px 32px",
      }}
    >
      <div className="text-center space-y-8">
        <BrandHeading size={48} />
        <div className="space-y-4">
          <div className="relative w-10 h-10 mx-auto flex items-center justify-center">
            <div className="absolute inset-0 rounded-full border-2 border-orange-500/15 animate-ping" />
            <div className="w-10 h-10 animate-spin rounded-full border-2 border-orange-500/20 border-t-orange-500" />
          </div>
          <p className="text-slate-600 text-sm">{t("common.loading")}</p>
        </div>
      </div>
    </div>
  )
}

export default LoadingState
