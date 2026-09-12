"use client";
import { BookOpenCheck, Landmark, Scale } from "lucide-react";
import { PageHeader } from "@/components/dashboard/page-header";
import { StatCard } from "@/components/dashboard/stat-card";
import { DataTable } from "@/components/dashboard/data-table";
import { StatusBadge } from "@/components/dashboard/status-badge";
import { useAdminJournalQuery, useAdminSettlementsQuery, useAdminTrialBalanceQuery } from "@/store/gateway-api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export default function Page(){
  const {data:tb}=useAdminTrialBalanceQuery();
  const {data:journal=[]}=useAdminJournalQuery();
  const {data:settlements=[]}=useAdminSettlementsQuery();
  const accounts=tb?.accounts??[];
  const debit=accounts.reduce((n:number,x:any)=>n+Number(x.debit||0),0);
  const credit=accounts.reduce((n:number,x:any)=>n+Number(x.credit||0),0);
  return <><PageHeader title="Gateway accounting" description="Double-entry journal accounting for provider clearing, merchant liabilities, gateway fees and settlements."/>
  <div className="grid gap-4 sm:grid-cols-3"><StatCard label="Total debits" value={`LSL ${debit.toFixed(2)}`} icon={<Scale/>}/><StatCard label="Total credits" value={`LSL ${credit.toFixed(2)}`} icon={<BookOpenCheck/>}/><StatCard label="Journal entries" value={journal.length} icon={<Landmark/>}/></div>
  <div className="mt-6 grid gap-5 xl:grid-cols-2"><Card><CardHeader><CardTitle>Trial balance</CardTitle></CardHeader><CardContent><div className="space-y-2">{accounts.length?accounts.map((a:any)=><div key={a.account_id} className="grid grid-cols-[70px_1fr_auto] gap-3 rounded-xl border bg-slate-50/60 p-3 text-sm"><span className="font-mono text-xs text-slate-500">{a.code}</span><div><p className="font-bold text-[#082b4d]">{a.name}</p><p className="text-xs capitalize text-slate-500">{a.type}</p></div><p className="font-black">{a.currency} {a.balance}</p></div>):<p className="py-8 text-center text-sm text-slate-500">Journal accounts are created automatically when the first financial transaction succeeds.</p>}</div></CardContent></Card><Card><CardHeader><CardTitle>Recent journal entries</CardTitle></CardHeader><CardContent><div className="space-y-2">{journal.slice(0,8).map((j:any)=><div key={j.id} className="rounded-xl border p-3"><div className="flex items-center justify-between gap-3"><div><p className="text-sm font-bold text-[#082b4d]">{j.description}</p><p className="mt-1 text-xs text-slate-500">{j.reference} · {j.posting_date}</p></div><StatusBadge status={j.status}/></div><div className="mt-2 flex flex-wrap gap-2">{j.lines?.map((l:any,i:number)=><span key={i} className="rounded-lg bg-slate-50 px-2 py-1 text-[11px] text-slate-600">{l.account_code}: Dr {l.debit} / Cr {l.credit}</span>)}</div></div>)}{!journal.length&&<p className="py-8 text-center text-sm text-slate-500">No journal entries yet.</p>}</div></CardContent></Card></div>
  <div className="mt-6"><h2 className="mb-3 text-lg font-black text-[#082b4d]">Settlements</h2><DataTable rows={settlements} empty="No settlement requests yet." columns={[{key:"id",label:"Settlement",render:(r:any)=><div><p className="font-bold">{r.id}</p><p className="text-xs text-slate-500">{r.reference}</p></div>},{key:"merchant",label:"Merchant",render:(r:any)=>r.merchant_id},{key:"amount",label:"Amount",render:(r:any)=><span className="font-black">{r.currency} {r.amount}</span>},{key:"status",label:"Status",render:(r:any)=><StatusBadge status={r.status}/>},{key:"created",label:"Created",render:(r:any)=>new Date(r.created_at).toLocaleString()}]}/></div></>;
}
