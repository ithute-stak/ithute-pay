"use client";
import Link from "next/link";
import { CheckCircle2 } from "lucide-react";
import { Button } from "@/components/ui/button";
export default function Page(){return <main className="grid min-h-screen place-items-center bg-slate-50 p-6"><div className="w-full max-w-lg rounded-3xl border bg-white p-8 text-center shadow-sm"><CheckCircle2 className="mx-auto h-12 w-12 text-emerald-600"/><h1 className="mt-4 text-2xl font-black text-[#082b4d]">Payment processing complete</h1><p className="mt-2 text-sm leading-6 text-slate-600">This return page is only a browser destination. The authoritative payment result comes from the provider callback/result endpoint and is reconciled by the gateway before merchant records are updated.</p><Button asChild className="mt-6"><Link href="/">Return to Ithute Pay Bridge</Link></Button></div></main>}
