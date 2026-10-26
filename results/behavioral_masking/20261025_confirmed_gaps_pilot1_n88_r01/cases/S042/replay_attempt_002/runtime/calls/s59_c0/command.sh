cd /app && python3 - <<'PY'
p='packages/core/src/entity/entity-methods-patch.ts'
s=open(p).read()
s=s.replace("""// @ts-expect-error
Number.prototype.changed = function (this: Entity, trait: Trait) {
    return setChanged(getEntityWorld(this), this, trait);
};""", """// @ts-expect-error
Number.prototype.changed = function (this: Entity, trait: Trait | RelationPair) {
    if (isRelationPair(trait)) {
        const pairCtx = trait[$internal];
        return setPairChanged(
            getEntityWorld(this),
            this,
            pairCtx.relation[$internal].trait,
            pairCtx.target as Entity
        );
    }
    return setChanged(getEntityWorld(this), this, trait);
};""")
open(p,'w').write(s)
print('entity patch updated')
PY
sed -n '1,50p' packages/core/src/entity/entity-methods-patch.ts