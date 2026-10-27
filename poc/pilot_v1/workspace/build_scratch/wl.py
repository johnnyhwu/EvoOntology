import json
qs=json.load(open('/Users/johnnyhwu/Desktop/EvoOntology/poc/build_input/construction_questions.json'))
json.dump({"questions":qs,"supplied_only":True,"include_history":False},open('/Users/johnnyhwu/Desktop/EvoOntology/poc/workspace/build_scratch/wl.json','w'),ensure_ascii=False)
