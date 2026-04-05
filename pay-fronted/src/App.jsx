// src/App.jsx
import { getUrlParam } from "@/lib/api"
import { useInvoice } from "@/hooks/useInvoice"
import { usePaymentMethod } from "@/hooks/usePaymentMethod"
import { useI18n } from "@/hooks/useI18n"
import useTheme from "@/hooks/useTheme"

import LoadingState from "@/components/LoadingState"
import ErrorState from "@/components/ErrorState"
import PaymentStepper from "@/components/PaymentStepper"

function App() {
  const { t } = useI18n()
  const { isDark, toggleTheme } = useTheme()
  const sysNo = getUrlParam("sys_no")
  const { invoice, loading, error, refetch } = useInvoice(sysNo)
  const {
    selectedCrypto,
    selectedChain,
    isSelecting,
    isEditing,
    error: paymentError,
    handleCryptoChange,
    handleChainChange,
    resetSelection,
    cancelEdit,
  } = usePaymentMethod(invoice, sysNo, refetch)

  if (loading) return <LoadingState />
  if (error) return <ErrorState error={error} onRetry={refetch} />
  if (!invoice) return <ErrorState error={t("error.invoiceNotFound")} onRetry={refetch} />

  return (
    <PaymentStepper
      invoice={invoice}
      selectedCrypto={selectedCrypto}
      selectedChain={selectedChain}
      isSelecting={isSelecting}
      isEditing={isEditing}
      paymentError={paymentError}
      handleCryptoChange={handleCryptoChange}
      handleChainChange={handleChainChange}
      resetSelection={resetSelection}
      cancelEdit={cancelEdit}
      refetch={refetch}
      isDark={isDark}
      toggleTheme={toggleTheme}
    />
  )
}

export default App
