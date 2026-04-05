const logoUrl = `${import.meta.env.BASE_URL}logo.svg`

function LogoMark({ size = 32, className = "" }) {
  const dimensionStyle = size ? { width: size, height: size } : undefined

  return (
    <img
      src={logoUrl}
      alt="Xcash logo"
      width={size}
      height={size}
      style={dimensionStyle}
      className={`object-contain ${className}`.trim()}
      draggable={false}
    />
  )
}

export default LogoMark
