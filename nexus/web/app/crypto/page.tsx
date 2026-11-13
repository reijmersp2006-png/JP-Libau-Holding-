import { Workstation } from "@/components/Workstation";

export default function Page() {
  return <Workstation classes={["crypto", "meme"]} title="Crypto" initial="BTC-EUR"
    intro="Koersonderzoek op opgeslagen Bitvavo-koersen in euro. Orderboek, funding, open interest en on-chainstromen zijn nog niet gekoppeld en staan daarom als ontbrekend, niet als nul." />;
}
