"use client";
import { PageHeader } from "@/components/dashboard/page-header";
import { DataTable } from "@/components/dashboard/data-table";
import { StatusBadge } from "@/components/dashboard/status-badge";
import { useAdminWebhookDeliveriesQuery } from "@/store/gateway-api";
export default function Page(){const {data=[],isLoading}=useAdminWebhookDeliveriesQuery();return <><PageHeader title="Webhooks & deliveries" description="Signed merchant notifications with delivery attempts, response codes and retry visibility."/><DataTable rows={data} empty={isLoading?"Loading webhook deliveries…":"No webhook deliveries yet."} columns={[{key:"url",label:"Endpoint",render:(r:any)=><p className="max-w-[360px] truncate font-medium text-[#082b4d]">{r.url||"—"}</p>},{key:"status",label:"Status",render:(r:any)=><StatusBadge status={r.status}/>},{key:"attempts",label:"Attempts",render:(r:any)=>r.attempt_count},{key:"http",label:"HTTP",render:(r:any)=>r.last_status_code||"—"},{key:"error",label:"Last error",render:(r:any)=><p className="max-w-[300px] truncate text-xs">{r.last_error||"—"}</p>},{key:"created",label:"Created",render:(r:any)=>new Date(r.created_at).toLocaleString()}]}/></>}
