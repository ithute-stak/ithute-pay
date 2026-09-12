import { PaymentForm } from "@/components/public/payment-form";
export default async function Page({ params }: { params: Promise<{ token: string }> }) { const { token } = await params; return <main className="soft-grid grid min-h-screen place-items-center bg-[#f4f8fb] p-5"><PaymentForm token={token} kind="checkout-sessions"/></main>; }
