#!/usr/bin/env python3
from __future__ import annotations
from serpent_core.effect_sdk import EffectCanvas
import colorsys, hashlib, math, random
from serpent_core.effects import Effect, EffectDefinition, EffectFrame, EffectParameters, EffectTarget
from serpent_core.effects.plugin import EffectParameterSpec, EffectPluginSpec

Colour=tuple[int,int,int]
def clamp(x): return max(0,min(255,round(x)))
def mix(a,b,t):
    t=max(0.0,min(1.0,t))
    return tuple(clamp(a[i]*(1-t)+b[i]*t) for i in range(3))
def vivid(rng):
    r,g,b=colorsys.hsv_to_rgb(rng.random(),rng.uniform(.84,1),rng.uniform(.92,1))
    return clamp(r*255),clamp(g*255),clamp(b*255)

class FireworksEffect(Effect):
    definition=EffectDefinition(id="fireworks",colours=1,animated=True,speed=True,spatial=True,
        minimum_spatial_positions=2,recommended_spatial_positions=12,degradation_policy="spatial")
    SEED="serpent-e7-fireworks-v1"
    @staticmethod
    def cadence(speed): return max(.55,1.45-.075*max(1,min(10,speed)))
    @staticmethod
    def launch_time(speed): return max(.24,.62-.025*max(1,min(10,speed)))
    @staticmethod
    def burst_time(speed): return max(.42,1.00-.045*max(1,min(10,speed)))
    @classmethod
    def rng(cls,i):
        d=hashlib.sha256(f"{cls.SEED}:{i}".encode()).digest()
        return random.Random(int.from_bytes(d[:8],"big"))
    @classmethod
    def firework(cls,i,target):
        rng=cls.rng(i); rows=max(1,target.rows); cols=max(1,target.columns)
        launch_col=rng.randrange(cols)
        burst_max=max(0,min(rows-1,math.ceil(rows*.66)-1))
        burst_row=rng.randint(0,burst_max)
        burst_col=max(0,min(cols-1,launch_col+rng.randint(-4,4)))
        return dict(launch_col=launch_col,burst_row=burst_row,burst_col=burst_col,
            radius=rng.uniform(1.35,3.15),colour=vivid(rng),
            phase=rng.random()*math.tau,spokes=rng.choice((6,7,8,9)))
    def indices(self,elapsed,p):
        c=self.cadence(p.speed); life=self.launch_time(p.speed)+self.burst_time(p.speed)
        newest=max(0,math.floor(max(0,elapsed)/c)); back=math.ceil(life/c)+2
        return range(max(0,newest-back),newest+1)
    @staticmethod
    def mouse_target(target): return target.rows<=1 or len(target.active_cells)<=3
    def keyboard(self,elapsed,p,target):
        bg=p.colour1; active=set(target.active_cells); c=self.cadence(p.speed)
        launch=self.launch_time(p.speed); burst=self.burst_time(p.speed); over={}
        def paint(r,col,intensity,colour):
            if (r,col) not in active or intensity<=0:return
            old=over.get((r,col))
            if old is None or intensity>=old[0]: over[(r,col)]=(intensity,colour)
        for i in self.indices(elapsed,p):
            age=elapsed-i*c
            if age<0: continue
            fw=self.firework(i,target); lc=fw["launch_col"]; br=fw["burst_row"]; bc=fw["burst_col"]; colour=fw["colour"]
            if age<launch:
                q=age/launch; rf=(target.rows-1)+(br-(target.rows-1))*q; cf=lc+(bc-lc)*q
                paint(round(rf),round(cf),1,colour)
                for tail,intensity in ((.10,.48),(.20,.24)):
                    tq=max(0,q-tail)
                    paint(round((target.rows-1)+(br-(target.rows-1))*tq),round(lc+(bc-lc)*tq),intensity,colour)
                continue
            ba=age-launch
            if ba>burst: continue
            q=ba/burst; fade=max(0,1-q); radius=fw["radius"]*min(1,q*1.35)
            paint(br,bc,.9*fade,colour)
            for s in range(fw["spokes"]):
                a=fw["phase"]+math.tau*s/fw["spokes"]; dr=math.sin(a); dc=math.cos(a)*1.45
                for frac,intensity in ((1,.98),(.68,.52)):
                    paint(round(br+dr*radius*frac),round(bc+dc*radius*frac),fade*intensity,colour)
        canvas=EffectCanvas(target,background=bg)
        for cell,(intensity,colour) in over.items():
            canvas.set(cell,mix(bg,colour,intensity))
        return canvas.frame()
    def mouse(self,elapsed,p,target):
        bg=p.colour1; c=self.cadence(p.speed); launch=self.launch_time(p.speed)
        flash=min(.34,self.burst_time(p.speed)*.48); chosen=None; intensity=0; newest=-1
        canonical=EffectTarget.full(6,22)
        for i in self.indices(elapsed,p):
            burst_at=i*c+launch; age=elapsed-burst_at
            if 0<=age<=flash and burst_at>=newest:
                chosen=self.firework(i,canonical)["colour"]; intensity=1-age/flash; newest=burst_at
        canvas=EffectCanvas(target,background=bg)
        if chosen is not None:
            colour=mix(bg,chosen,intensity)
            for cell in target.active_cells:
                canvas.set(cell,colour)
        return canvas.frame()
    def render(self,elapsed,parameters,target):
        target.validate()
        return self.mouse(elapsed,parameters,target) if self.mouse_target(target) else self.keyboard(elapsed,parameters,target)

SERPENT_EFFECT_PLUGINS=(EffectPluginSpec(
    id="fireworks",name="Fireworks",
    description="Autonomous bottom-launched fireworks with random upper burst heights, vivid procedural hues and random sizes. Mouse targets rest on the background and flash the current burst colour.",
    effect_class=FireworksEffect,input_capabilities=(),render_targets=("keyboard","mouse"),
    parameters=(
        EffectParameterSpec(id="colour1",label="Background Colour",kind="colour",default=(4,4,12)),
        EffectParameterSpec(id="speed",label="Speed",kind="integer",default=5,minimum=1,maximum=10),
    )),)
for plugin in SERPENT_EFFECT_PLUGINS: plugin.validate()
