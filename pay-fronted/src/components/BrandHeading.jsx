import LogoMark from "@/components/LogoMark"

function BrandHeading({ size = 40, className = "" }) {
  return (
    <div className={`flex items-center space-x-3 ${className}`}>
      <LogoMark size={size} className="shrink-0" />
      <div className="text-left">
        <h1
          className="font-bold text-2xl bg-gradient-to-r from-orange-400 via-orange-300 to-amber-300 bg-clip-text text-transparent tracking-wide"
          style={{ fontFamily: "'Orbitron', 'Space Grotesk', sans-serif" }}
        >
          Xcash
        </h1>
      </div>
    </div>
  )
}

export default BrandHeading
