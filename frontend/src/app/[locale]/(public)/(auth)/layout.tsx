import { BackgroundGradientAnimation } from "@/components/ui/background-gradient-animation";

export default function AuthLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="relative flex min-h-[calc(100vh-5rem)] w-full flex-col">
      {/* Même Background Gradient Animation que la landing page */}
      <BackgroundGradientAnimation
        containerClassName="fixed inset-0 -z-10 h-full w-full pointer-events-none"
        interactive={true}
      />
      <div className="relative z-10 flex w-full grow flex-col">{children}</div>
    </div>
  );
}
