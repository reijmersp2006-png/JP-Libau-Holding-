import { Placeholder } from "@/components/Placeholder";

export default function Page() {
  return <Placeholder spec={{
    title: "Crypto Terminal", phase: 2,
    purpose: "Diepte-analyse per munt: grafieken met indicatoren, orderboek, funding, open interest en on-chain stromen.",
    existing: ["Uur- en dagkoersen van Bitvavo voor BTC, ETH, SOL, XRP (DELAYED)", "Crypto-afdeling handelt op papier: kern + noodrem op het 200-dagengemiddelde", "Volume- en koersalarmen van de verkenners"],
    next: ["Candlestick-grafiek (TradingView Lightweight Charts) met volume, RSI, MACD, VWAP", "Order- en positiemarkeringen op de grafiek", "Funding rates en open interest (alleen lezen)", "On-chain: exchange in/uit-stromen en whale-transacties"],
    sources: ["Bitvavo publieke API (gratis, geen sleutel)", "On-chain: Glassnode/CryptoQuant/Etherscan (betaald of met limieten)", "Funding/OI: publieke futures-API’s van exchanges (alleen data, geen derivatenhandel)"],
  }} />;
}
