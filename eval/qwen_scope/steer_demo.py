"""Qwen-Scope steering with CONTRASTIVE feature selection: concept-active minus neutral-active -> the
concept-specific feature, not generic syntax features. Then steer at a tuned coeff."""
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
M="/model"; LAYER=14
tok=AutoTokenizer.from_pretrained(M, trust_remote_code=True)
print("loading...", flush=True)
model=AutoModelForCausalLM.from_pretrained(M, trust_remote_code=True, dtype=torch.float16, device_map="cuda").eval()
sae=torch.load("/sae/layer14.sae.pt", map_location="cuda")
W_enc=sae["W_enc"].float(); W_dec=sae["W_dec"].float(); b_enc=sae["b_enc"].float(); b_dec=sae["b_dec"].float()
layers=model.model.layers
def feat_means(texts):
    """mean SAE feature activations over all tokens of several texts"""
    acc=torch.zeros(W_enc.shape[0],device="cuda"); n=0; cap={}
    hh=layers[LAYER].register_forward_hook(lambda m,i,o: cap.__setitem__("h",(o[0] if isinstance(o,tuple) else o).detach()))
    for t in texts:
        with torch.no_grad(): model(**tok(t,return_tensors="pt").to("cuda"))
        for x in cap["h"][0].float():
            acc+=torch.relu(W_enc@(x-b_dec)+b_enc); n+=1
    hh.remove(); return acc/n
concept=["The ocean waves crashed on the shore.","Deep blue sea water full of fish and coral.","Sailing across the vast ocean, the waves were huge."]
neutral=["The meeting is scheduled for Tuesday afternoon.","She calculated the quarterly budget report.","The software update fixed several bugs."]
cm=feat_means(concept); nm=feat_means(neutral)
diff=cm-nm; feat=diff.topk(5).indices.tolist()
print(f"CONTRASTIVE ocean features (concept-neutral): {feat}", flush=True)
f0=feat[0]; direction=W_dec[:,f0]; direction=direction/direction.norm()
# resid norm for scaling
cap={}; hh=layers[LAYER].register_forward_hook(lambda m,i,o: cap.__setitem__("h",(o[0] if isinstance(o,tuple) else o).detach()))
with torch.no_grad(): model(**tok("Hello there.",return_tensors="pt").to("cuda"))
hh.remove(); resnorm=cap["h"][0].norm(dim=-1).mean().item()
COEFF=[0.0]
def steer(m,i,o):
    v=COEFF[0]*resnorm*direction
    if isinstance(o,tuple): return (o[0]+v.to(o[0].dtype),)+tuple(o[1:])
    return o+v.to(o.dtype)
layers[LAYER].register_forward_hook(steer)
prompt="My favorite thing to think about is"
def gen():
    e=tok(prompt,return_tensors="pt").to("cuda")
    with torch.no_grad(): out=model.generate(**e,max_new_tokens=28,do_sample=False)
    return tok.decode(out[0,e["input_ids"].shape[1]:],skip_special_tokens=True).replace("\n"," ")
for c in [0.0,0.1,0.2,0.35]:
    COEFF[0]=c; print(f"  coeff={c}: {gen()}", flush=True)
