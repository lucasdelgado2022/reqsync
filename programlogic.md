The main idea is to have a program that would allow me to sync requirements to 3dexperience (from now on 3dx).

3DX will only hold the requirements, no edition will take place directly on 3dx.

We'll have the requirements on an excel file. The excel file will have a format indicating hierarchy between diferent requirments, which must be defined, but for now, we'll asume 4 columns on the excel file (title or id, content (only for requirements),parent id,type (req or chapter)).

There are 3 types of objects in 3dx. Specification, Chapters, and Requirements, the specification is not indicated in the excel file, but it's the holder of all the content of the excel and must be created. The specification can only contain chapters, so the top level requirements on the excel file are always chapters. chapters can contain chapters or requirements. requirements can contain requiriments.

My idea is to have a script that would read the structure on the excel, store it on a postgre db that i have already running (see schema.sql) and push the structure to 3dx using the methods defined on reqsync.xlsx that are actually written on tdxoperations.py. Then if i rerun the script it should detect changes on the excel comparing to the db, and apply this changes. 

On the first commit:

1- read the excel, and map to the db each chapter, and requirement, and its relations. The title must be used as the internal id, and the 3dexperience id will be gotten later.

2- use the create operation to create spec, chapters and requirements. fill the db with the corresponding id.

3- create the spec-chapter, chapter-chapter, chapter-req and req-req relations and store the relations ids.

4- Release chapters, requirement and specs

Second spec:

This part is more complex.

1- read the excel, detect changes on content, and in relations. we'll have to store which relations must be added, which must be deleted and which content must be modified.

2- revise and update and create new reqs if exists, and here the problem begins. because all the structure is released, we are forced to revise all the parents of a children in order to change it, for example, if my extructure is A->A.1->A.1.1 and i want to change the content of A.1.1 I should create a new revision of A.1.1, A.1, A and the specification. So we need to determine all the parents affected, and revise and change the content of everything that needs to be change. If i need to change the relations, delete or add childrens, that would also mean i have to update all the parents. Store the new id in the db, we must keep the last id also somewh

3- reconsile relations ids. If i revise a parent, all its children are kept on the original revision, but new revision ids are generated, in order to apply the changes i need to remove the original revision of its children and add the new one, in order to do that i need to reconcile the relations ids using the get_structure methods and update them on the db. here the index problem arises, we need to keep track of which relations we are expecting to find and keep calling until they all appear, we may expect from 1 to 5 minutes to get a full indexation.

4- delete old revisions and add new revisions and update relations ids.

5- release the new strucure



First commit step by step:

check if db is empty for determining if we are talking about the first commit.

1- Create root spec with an editable name that must be defined at the beginning of the script, you must use create_spec for that. Store the spec id on the database.

2- Read the excel file and extract a list with requirements, chapters, and relations. Store each requirement, chapter and relation on the db, store internal id and content for the requirements, you won't have the 3dx id yet. Add the spec to top level chapter relationships too. Check that all top levels are chapters, if no, throw an error.

3- Create requirements and chapters using create_several_reqs and create_several_chapters, you should put all the requirements on a same call, and all the chapters on a same call. Store the ids of each req and chapter on the db

4- Create all spec-chapter relations using relate_several_chapter_req, do the same for chapter-chapter relate_several_chapter_chapter, chapter-req relate_several_chapter_req and req-req relate_several_req_req. store the relations ids on the db.

5- Release the structure using release_several_reqs release_several_chapters and release_spec.


2nd+ commit:

1- Read the excel file and create a list of chapters, requirements and relations, just in the same way as in the first commit.

2- Compare the new information to the db, we could expect different changes:
a- new requirements or chapters are created.
b- chapters or requirements are removed.
c- requirements content/description are edited.
d- new relations are created
e- relations are deleted.


3- Identify what needs to be changed:
a- create a list for all new requirements and one for all new chapters.
b- removals will not automatically create any change, because a removal of a requirement of chapter, means that a relation is also removed, so we won't take any action here (we want to keep the deleted requirement in the db but not in the structure)
c- when a requirement is edited, it must be revised, also, its parent must be revised, and its parent, and so on, all the way to the spec. we should mark those for revision, and also add the content change on the requirement.
d/e- when a relation is added or created, the parent must be revised, and also its parent all the way to the spect 

5-revise everything that must be revised, but do not use the same operation for parent and child, keep the operations separated based on the hierarchy level, this revise operation allows to change the content of the requirements too. store the new ids, but keep the old id on the db (we don't need to keep all ids, but just the newer and the previous one, so a current and old id column should be enough)

6-At this point we have at least a new revision of the spec if something was changed. Also, we have a new revision of everything modified. I want to keep the structure order, this will make me do some strange things. Also 3dexperience have some limitations, Let's supposed i have the following structure:

Spec rev1 -> chap A rev1 -> req A.1 rev1 -> req A.1.1 rev 1

If I want to modify req A.1.1 rev 1, I'll need to create a new revision of everything. So I'll have

req A.1.1 rev2 which is a leave

req A.1 rev2 which contains req A.1.1 rev 1

chap A rev2 which contains  req A.1 rev1 -> req A.1.1 rev 1

Spec rev2 which contains chap A rev1 -> req A.1 rev1 -> req A.1.1 rev 1

the issue is that the relations from A.1 rev2 to A.1.1 rev1, from chap A rev2 to req A.1 rev1 and from Spec rev2 to chap A rev1 have a new id, and this id is not return by the revising operation call. this means that we don't actually now how the structure is made yet. and the only way to now the relations names is to call get_structure on spec or chapter level, but because req A.1 rev2 and req A.1.1 rev2 are not in any chapter, we can't now their relation id. Also, when adding or deleting relationships, the structure gets mixed and we lost the original order.


what we could do:

delete all the relations from Spec rev2 childrens, we need to find their id doing a get_structure_spec call, because of the index problem, we should wait until we see each chapter declared on the db as top level. scan chap A rev2 with get_structure_chapter, we should see each of the declared childs on the db. at this point, we can't inferred more relationships ids. 
