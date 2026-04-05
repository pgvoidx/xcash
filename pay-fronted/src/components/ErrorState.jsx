import BrandHeading from "@/components/BrandHeading"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { useI18n } from "@/hooks/useI18n"

function ErrorState({ error, onRetry }) {
  const { t } = useI18n()

  return (
    <div className="min-h-svh bg-[var(--app-bg)] flex flex-col items-center justify-center p-4"
      style={{
        backgroundImage: "radial-gradient(circle, rgba(255,255,255,0.035) 1px, transparent 1px)",
        backgroundSize: "32px 32px",
      }}
    >
      <div className="w-full max-w-md space-y-6">
        <div className="flex justify-center">
          <BrandHeading size={36} />
        </div>
        <Card>
          <CardHeader>
            <CardTitle className="text-red-400">{t("error.title")}</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-slate-500 mb-5">{error}</p>
            <Button
              onClick={onRetry}
              className="w-full font-semibold shadow-[0_0_24px_rgba(249,115,22,0.2)] cursor-pointer"
            >
              {t("common.retry")}
            </Button>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

export default ErrorState
