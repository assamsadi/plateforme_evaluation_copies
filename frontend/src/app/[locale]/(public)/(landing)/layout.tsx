import AosInit from "@/components/landing/ui/aos-init";
import Footer from "@/components/landing/ui/footer";

export default function LandingLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <>
      <AosInit />
      <main className="relative flex grow flex-col">{children}</main>
      <Footer />
    </>
  );
}
