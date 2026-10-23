import {useEffect,useState} from 'react';
import {defaultProfile,type Profile,type Rules,type Bundle} from './catalog';
import type {BuyerContext,BundlePayload,RatingsPayload,Analysis,FinalPayload,Decision,Check} from './contracts';
export type Status='setup'|'negotiating'|'awaiting-buyer'|'declined'|'completed'|'invalid';
export type Session={id:string;profile:Profile;profileReady:boolean;rules:Rules;sellerReady:boolean;status:Status;startedAt:number;bundles:Bundle[];selection:string|null;context:BuyerContext|null;offers:BundlePayload|null;ratings:RatingsPayload|null;analysis:Analysis|null;final:FinalPayload|null;finalOffer:Bundle|null;decision:Decision|null;checks:Check[];revision:number;events:{id:string;text:string;time:number}[]};
const key='tandem.demo.v3';
export function fresh():Session{return {id:crypto.randomUUID(),profile:{...defaultProfile},profileReady:false,rules:{maxItems:4,maxDiscount:15},sellerReady:false,status:'setup',startedAt:0,bundles:[],selection:null,context:null,offers:null,ratings:null,analysis:null,final:null,finalOffer:null,decision:null,checks:[],revision:0,events:[]};}
function read():Session{try{const s=JSON.parse(localStorage.getItem(key)||'null'); if(s?.id && Array.isArray(s.bundles))return s;}catch{}return fresh();}
let current=read();
try{if(!localStorage.getItem(key))localStorage.setItem(key,JSON.stringify(current));}catch{}
const listeners=new Set<()=>void>();
const channel=typeof BroadcastChannel!=='undefined'?new BroadcastChannel('tandem.demo'):null;
function refresh(){current=read();listeners.forEach(fn=>fn());}
window.addEventListener('storage',e=>{if(e.key===key)refresh();});
channel?.addEventListener('message',refresh);
export function update(change:(s:Session)=>Session){const next=change(read());next.revision++;localStorage.setItem(key,JSON.stringify(next));current=next;listeners.forEach(fn=>fn());channel?.postMessage('update');}
export function event(s:Session,text:string):Session{return {...s,events:[...s.events,{id:crypto.randomUUID(),text,time:Date.now()}].slice(-30)};}
export function reset(){const next=fresh();localStorage.setItem(key,JSON.stringify(next));current=next;listeners.forEach(fn=>fn());channel?.postMessage('reset');}
export function useSession(){const [session,set]=useState(current);useEffect(()=>{const fn=()=>set(current);listeners.add(fn);return ()=>{listeners.delete(fn)};},[]);return session;}
