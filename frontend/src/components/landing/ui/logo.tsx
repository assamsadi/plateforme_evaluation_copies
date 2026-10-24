import Image from "next/image";
import logo from "../../../../public/images/logo-c2pct.png";

import { Link } from "@/i18n/navigation";

export default function Logo() {
  return (
    <Link href="/" className="inline-flex shrink-0 items-center" aria-label="Accueil">
      <Image
        src={logo}
        alt="Logo C2PCT Assess"
        width={1324}
        height={318}
        priority
        className="h-16 w-auto sm:h-20 md:h-24 object-contain"
      />
    </Link>
  );
}
