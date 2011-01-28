# # needed from env:
# IADIST=''
# # e.g. foo.bar.org
# ACSHOST=
# ACSPASS=

for rsrc in 'urn:uuid:0df6f344-7ce9-4038-885e-e02db34f2891' 'urn:uuid:309fc37a-3d66-4a64-8f5a-cf81729513f4' 'urn:uuid:623d8da5-7f55-4189-8661-c0f377cb4e5c' 'urn:uuid:724ffe16-b878-4ad4-b76d-144ffdd89b93' 'urn:uuid:7f192e62-13f5-4a62-af48-be4bea67e109' 'urn:uuid:87b5008d-17f9-41c5-aba8-81076bc14c39' 'urn:uuid:89a6a73f-f05f-415b-8f81-918aebd0b550' 'urn:uuid:a0babb2e-0557-4439-b2c5-c4c3d8d65690' 'urn:uuid:a8b600e2-32fd-4aeb-a2b5-641103583254' 'urn:uuid:c5b49dd0-efad-4cb2-a85e-196868092104' 'urn:uuid:f095206e-0aa2-4b99-b077-bde50edbaead'; do
    python acs4cmd.py --password=$ACSPASS --debug --resource=$rsrc --distributor=$IADIST  $ACSHOST request DistributionRights update --distributionType=loan --returnable=true --available=1 --permissions=sample_permissions.xml --debug
done
