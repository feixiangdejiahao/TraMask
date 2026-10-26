python3 -I -c '
import hashlib,json,os,stat,sys
root=sys.argv[1];rows=[]
for path in sys.argv[2:]:
    target=os.path.join(root,path)
    row={'"'"'path'"'"':path,'"'"'exists'"'"':False,'"'"'kind'"'"':'"'"'absent'"'"','"'"'bytes'"'"':None,'"'"'sha256'"'"':None}
    try:info=os.lstat(target)
    except FileNotFoundError:
        rows.append(row)
        continue
    row.update(exists=True,mode=stat.S_IMODE(info.st_mode))
    if stat.S_ISREG(info.st_mode):
        row['"'"'kind'"'"']='"'"'file'"'"'
        with open(target,'"'"'rb'"'"') as stream:data=stream.read()
    elif stat.S_ISLNK(info.st_mode):
        row['"'"'kind'"'"']='"'"'symlink'"'"'
        row['"'"'link_target'"'"']=os.readlink(target)
        data=os.fsencode(row['"'"'link_target'"'"'])
    else:
        row['"'"'kind'"'"']='"'"'directory'"'"' if stat.S_ISDIR(info.st_mode) else '"'"'special'"'"'
        rows.append(row)
        continue
    row.update(bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
    rows.append(row)
print(json.dumps({'"'"'paths'"'"':rows,'"'"'hash_policy'"'"':'"'"'file_bytes_or_symlink_target_bytes'"'"'}))
' /app src/entity/actions/update/updateItemParams/requiredIfConditions.ts src/entity/actions/update/updateItemParams/updateItemParams.ts src/schema/actions/dto/getSchemaDTO/any.ts src/schema/actions/dto/getSchemaDTO/anyOf.ts src/schema/actions/dto/getSchemaDTO/list.ts src/schema/actions/dto/getSchemaDTO/map.ts src/schema/actions/dto/getSchemaDTO/primitive.ts src/schema/actions/dto/getSchemaDTO/record.ts src/schema/actions/dto/getSchemaDTO/set.ts src/schema/actions/dto/types.ts src/schema/actions/fromDTO/fromSchemaDTO/anyOf.ts src/schema/actions/jsonSchemer/formattedValue/item.ts src/schema/actions/jsonSchemer/formattedValue/map.ts src/schema/actions/jsonSchemer/formattedValue/shared.ts src/schema/actions/parse/errors.ts src/schema/actions/parse/item.ts src/schema/actions/parse/map.ts src/schema/actions/parse/utils.ts src/schema/actions/zodSchemer/formatter/item.ts src/schema/actions/zodSchemer/formatter/map.ts src/schema/actions/zodSchemer/formatter/utils.ts src/schema/actions/zodSchemer/parser/item.ts src/schema/actions/zodSchemer/parser/map.ts src/schema/actions/zodSchemer/parser/utils.ts src/schema/any/schema_.ts src/schema/anyOf/schema_.ts src/schema/binary/schema_.ts src/schema/boolean/schema_.ts src/schema/item/errors.ts src/schema/item/schema.ts src/schema/list/schema_.ts src/schema/map/schema.ts src/schema/map/schema_.ts src/schema/null/schema_.ts src/schema/number/schema_.ts src/schema/record/schema_.ts src/schema/set/schema_.ts src/schema/string/schema_.ts src/schema/types/index.ts src/schema/types/schemaProps.ts src/schema/utils/checkRequiredIf.ts src/schema/utils/checkSchemaProps.ts src/schema/utils/errors.ts