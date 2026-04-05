export const formatChainName = (chain) => {
  if (!chain) {
    return "未指定网络"
  }

  return chain
    .split('-')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
}
