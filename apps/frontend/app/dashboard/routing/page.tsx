"use client";

import { FormEvent, useMemo, useState } from "react";
import { Building2, Link2, Send, Webhook } from "lucide-react";
import { PageHeader } from "@/components/dashboard/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { DataTable } from "@/components/dashboard/data-table";
import {
  useAdminApplicationsQuery,
  useAdminMerchantsQuery,
  useCreateMerchantRoutingKeyMutation,
  useCreateMerchantSettlementAccountMutation,
  useCreateMerchantWebhookEndpointMutation,
  useGatewayMerchantProfilesQuery,
  useMerchantRoutingKeysQuery,
  useMerchantSettlementAccountsQuery,
  useMerchantWebhookEndpointsQuery,
  useSaveGatewayMerchantProfileMutation,
} from "@/store/gateway-api";

export default function Page(){
  const {data:merchants=[]}=useAdminMerchantsQuery();
  const {data:apps=[]}=useAdminApplicationsQuery();
  const {data:profiles=[]}=useGatewayMerchantProfilesQuery();
  const [merchantId,setMerchantId]=useState("");
  const {data:keys=[]}=useMerchantRoutingKeysQuery(merchantId,{skip:!merchantId});
  const {data:accounts=[]}=useMerchantSettlementAccountsQuery(merchantId,{skip:!merchantId});
  const {data:webhooks=[]}=useMerchantWebhookEndpointsQuery(merchantId,{skip:!merchantId});
  const [saveProfile]=useSaveGatewayMerchantProfileMutation();
  const [addKey]=useCreateMerchantRoutingKeyMutation();
  const [addAccount]=useCreateMerchantSettlementAccountMutation();
  const [addWebhook]=useCreateMerchantWebhookEndpointMutation();
  const profile=useMemo(()=>profiles.find((x:any)=>x.merchant_id===merchantId),[profiles,merchantId]);
  const [profileForm,setProfileForm]=useState<any>({merchant_number:"",sector:"school",default_application_id:"",auto_settle:true,settlement_delay_seconds:0,enabled:true});
  const [keyForm,setKeyForm]=useState<any>({key_type:"school_number",key_value:""});
  const [accountForm,setAccountForm]=useState<any>({provider:"mpesa",account_type:"business_shortcode",account_reference:"",currency:"LSL",label:"Primary M-Pesa settlement",is_default:true,enabled:true});
  const [webhookForm,setWebhookForm]=useState<any>({application_id:"",url:"",event_types:"payment.succeeded,payment.failed,settlement.succeeded"});
  const [createdSecret,setCreatedSecret]=useState("");

  function choose(id:string){setMerchantId(id);const p=profiles.find((x:any)=>x.merchant_id===id);setProfileForm(p?{merchant_number:p.merchant_number||"",sector:p.sector||"general",default_application_id:p.default_application_id||"",auto_settle:p.auto_settle,settlement_delay_seconds:p.settlement_delay_seconds||0,enabled:p.enabled}:{merchant_number:"",sector:"school",default_application_id:"",auto_settle:true,settlement_delay_seconds:0,enabled:true});}
  async function submitProfile(e:FormEvent){e.preventDefault();await saveProfile({merchantId,body:{...profileForm,default_application_id:profileForm.default_application_id||null}}).unwrap();}
  async function submitKey(e:FormEvent){e.preventDefault();await addKey({merchantId,body:keyForm}).unwrap();setKeyForm({...keyForm,key_value:""});}
  async function submitAccount(e:FormEvent){e.preventDefault();await addAccount({merchantId,body:accountForm}).unwrap();setAccountForm({...accountForm,account_reference:""});}
  async function submitWebhook(e:FormEvent){e.preventDefault();const r=await addWebhook({merchantId,body:{application_id:webhookForm.application_id||null,url:webhookForm.url,event_types:webhookForm.event_types.split(",").map((x:string)=>x.trim()).filter(Boolean)}}).unwrap();setCreatedSecret(r.signing_secret);setWebhookForm({...webhookForm,url:""});}

  return <><PageHeader title="Client routing & settlement" description="Map school/company identifiers to gateway merchants, store where each client's net funds must be paid, and configure signed callbacks into the client's own platform."/>
  <Card className="mb-5"><CardContent className="pt-6"><select className="h-11 w-full rounded-xl border bg-white px-3 text-sm" value={merchantId} onChange={e=>choose(e.target.value)}><option value="">Select client merchant</option>{merchants.map((m:any)=><option key={m.id} value={m.id}>{m.name}</option>)}</select></CardContent></Card>
  {!merchantId?<div className="rounded-2xl border border-dashed p-12 text-center text-sm text-slate-500">Select a merchant to configure its gateway identity, routing, settlement destination and client callback.</div>:<div className="grid gap-5 xl:grid-cols-2">
    <Card><CardHeader><CardTitle className="flex items-center gap-2"><Building2 className="h-4 w-4"/>Gateway client profile</CardTitle></CardHeader><CardContent><form className="grid gap-3" onSubmit={submitProfile}><Input placeholder="Merchant number, e.g. SCH001" value={profileForm.merchant_number} onChange={e=>setProfileForm({...profileForm,merchant_number:e.target.value})}/><select className="h-11 rounded-xl border bg-white px-3 text-sm" value={profileForm.sector} onChange={e=>setProfileForm({...profileForm,sector:e.target.value})}><option value="school">School</option><option value="microloan">Microloan</option><option value="insurance">Insurance</option><option value="retail">Retail</option><option value="general">General</option></select><select className="h-11 rounded-xl border bg-white px-3 text-sm" value={profileForm.default_application_id} onChange={e=>setProfileForm({...profileForm,default_application_id:e.target.value})}><option value="">First active application</option>{apps.filter((a:any)=>a.merchant_id===merchantId).map((a:any)=><option key={a.id} value={a.id}>{a.name}</option>)}</select><Input type="number" min={0} placeholder="Settlement delay seconds" value={profileForm.settlement_delay_seconds} onChange={e=>setProfileForm({...profileForm,settlement_delay_seconds:Number(e.target.value)})}/><label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={profileForm.auto_settle} onChange={e=>setProfileForm({...profileForm,auto_settle:e.target.checked})}/>Automatically send net funds to client</label><label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={profileForm.enabled} onChange={e=>setProfileForm({...profileForm,enabled:e.target.checked})}/>Client enabled for routed payments</label><Button>Save client profile</Button></form></CardContent></Card>
    <Card><CardHeader><CardTitle className="flex items-center gap-2"><Link2 className="h-4 w-4"/>Routing identifiers</CardTitle></CardHeader><CardContent><form className="grid gap-2 sm:grid-cols-[1fr_1fr_auto]" onSubmit={submitKey}><select className="h-11 rounded-xl border bg-white px-3 text-sm" value={keyForm.key_type} onChange={e=>setKeyForm({...keyForm,key_type:e.target.value})}><option value="school_number">School number</option><option value="company_number">Company number</option><option value="merchant_number">Merchant number</option><option value="policy_provider">Policy provider</option></select><Input required placeholder="Identifier" value={keyForm.key_value} onChange={e=>setKeyForm({...keyForm,key_value:e.target.value})}/><Button>Add</Button></form><div className="mt-4"><DataTable rows={keys} empty="No extra routing identifiers." columns={[{key:"type",label:"Type",render:(r:any)=>r.key_type},{key:"value",label:"Value",render:(r:any)=><code>{r.key_value}</code>},{key:"state",label:"State",render:(r:any)=>r.enabled?"Enabled":"Disabled"}]}/></div></CardContent></Card>
    <Card><CardHeader><CardTitle className="flex items-center gap-2"><Send className="h-4 w-4"/>Net settlement destination</CardTitle></CardHeader><CardContent><form className="grid gap-2 sm:grid-cols-2" onSubmit={submitAccount}><select className="h-11 rounded-xl border bg-white px-3 text-sm" value={accountForm.account_type} onChange={e=>setAccountForm({...accountForm,account_type:e.target.value})}><option value="business_shortcode">M-Pesa business shortcode (B2B)</option><option value="msisdn">M-Pesa phone/MSISDN (B2C)</option></select><Input required placeholder="Shortcode or phone" value={accountForm.account_reference} onChange={e=>setAccountForm({...accountForm,account_reference:e.target.value})}/><Input placeholder="Label" value={accountForm.label} onChange={e=>setAccountForm({...accountForm,label:e.target.value})}/><Input placeholder="Currency" value={accountForm.currency} onChange={e=>setAccountForm({...accountForm,currency:e.target.value})}/><Button className="sm:col-span-2">Add settlement account</Button></form><div className="mt-4"><DataTable rows={accounts} empty="No settlement destination configured. Successful collections will be held as unconfigured." columns={[{key:"type",label:"Type",render:(r:any)=>r.account_type},{key:"account",label:"Destination",render:(r:any)=><code>{r.account_reference}</code>},{key:"default",label:"Default",render:(r:any)=>r.is_default?"Yes":"No"}]}/></div></CardContent></Card>
    <Card><CardHeader><CardTitle className="flex items-center gap-2"><Webhook className="h-4 w-4"/>Client payment callback</CardTitle></CardHeader><CardContent><form className="grid gap-2" onSubmit={submitWebhook}><select className="h-11 rounded-xl border bg-white px-3 text-sm" value={webhookForm.application_id} onChange={e=>setWebhookForm({...webhookForm,application_id:e.target.value})}><option value="">Default application</option>{apps.filter((a:any)=>a.merchant_id===merchantId).map((a:any)=><option key={a.id} value={a.id}>{a.name}</option>)}</select><Input required type="url" placeholder="https://school.example/api/payments/ithute" value={webhookForm.url} onChange={e=>setWebhookForm({...webhookForm,url:e.target.value})}/><Input placeholder="Comma-separated event types" value={webhookForm.event_types} onChange={e=>setWebhookForm({...webhookForm,event_types:e.target.value})}/><Button>Add signed callback</Button></form>{createdSecret&&<div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs"><p className="font-bold text-amber-900">Signing secret — copy it now</p><code className="mt-1 block break-all text-amber-800">{createdSecret}</code></div>}<div className="mt-4"><DataTable rows={webhooks} empty="No client callback configured." columns={[{key:"url",label:"URL",render:(r:any)=><span className="break-all text-xs">{r.url}</span>},{key:"events",label:"Events",render:(r:any)=><span className="text-xs">{r.event_types?.length?r.event_types.join(", "):"All"}</span>}]}/></div></CardContent></Card>
  </div>}</>;
}
