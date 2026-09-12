targetScope = 'resourceGroup'

@allowed(['westeurope'])
param location string = 'westeurope'
@minLength(3)
@maxLength(16)
param prefix string = 'mosaique-r1'
@description('Operator IPv4 CIDR, normally a single /32. Never use 0.0.0.0/0.')
param operatorCidr string
@secure()
param sshPublicKey string
@description('Exact Canonical Ubuntu 24.04 marketplace version; resolve and record before deployment. No latest.')
param ubuntuImageVersion string
param adminUsername string = 'mosaique'

var hosts = [
  { role: 'app', size: 'Standard_B2s', ip: '10.20.1.4', subnet: 'app', cidr: '10.20.1.0/24' }
  { role: 'gpu', size: 'Standard_NC4as_T4_v3', ip: '10.20.2.4', subnet: 'gpu', cidr: '10.20.2.0/24' }
]
var tags = { project: 'mosaique', milestone: 'two-user', slice: 'R1' }
resource nsgs 'Microsoft.Network/networkSecurityGroups@2024-05-01' = [
  for host in hosts: {
    name: '${prefix}-${host.role}-nsg'
    location: location
    tags: tags
    properties: {
      securityRules: concat(
        host.role == 'app'
          ? [
              {
                name: 'operator-ssh'
                properties: {
                  priority: 100
                  direction: 'Inbound'
                  access: 'Allow'
                  protocol: 'Tcp'
                  sourcePortRange: '*'
                  destinationPortRange: '22'
                  sourceAddressPrefix: operatorCidr
                  destinationAddressPrefix: host.ip
                }
              }
              {
                name: 'web'
                properties: {
                  priority: 110
                  direction: 'Inbound'
                  access: 'Allow'
                  protocol: 'Tcp'
                  sourcePortRange: '*'
                  destinationPortRanges: ['80', '443']
                  sourceAddressPrefix: 'Internet'
                  destinationAddressPrefix: host.ip
                }
              }
              {
                name: 'turn-tcp'
                properties: {
                  priority: 120
                  direction: 'Inbound'
                  access: 'Allow'
                  protocol: 'Tcp'
                  sourcePortRange: '*'
                  destinationPortRanges: ['3478', '5349']
                  sourceAddressPrefix: 'Internet'
                  destinationAddressPrefix: host.ip
                }
              }
              {
                name: 'turn-udp'
                properties: {
                  priority: 130
                  direction: 'Inbound'
                  access: 'Allow'
                  protocol: 'Udp'
                  sourcePortRange: '*'
                  destinationPortRanges: ['3478', '49160-49200']
                  sourceAddressPrefix: 'Internet'
                  destinationAddressPrefix: host.ip
                }
              }
            ]
          : [
              {
                name: 'app-to-asr-and-ssh'
                properties: {
                  priority: 100
                  direction: 'Inbound'
                  access: 'Allow'
                  protocol: 'Tcp'
                  sourcePortRange: '*'
                  destinationPortRanges: ['8080', '22']
                  sourceAddressPrefix: '10.20.1.4'
                  destinationAddressPrefix: host.ip
                }
              }
            ],
        [
          // Override Azure's default AllowVNetInBound: only the rules above admit traffic.
          {
            name: 'deny-other-inbound'
            properties: {
              priority: 4096
              direction: 'Inbound'
              access: 'Deny'
              protocol: '*'
              sourcePortRange: '*'
              destinationPortRange: '*'
              sourceAddressPrefix: '*'
              destinationAddressPrefix: '*'
            }
          }
        ]
      )
    }
  }
]
resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: '${prefix}-vnet'
  location: location
  tags: tags
  properties: {
    addressSpace: { addressPrefixes: ['10.20.0.0/16'] }
    subnets: [
      for (host, i) in hosts: {
        name: host.subnet
        properties: {
          addressPrefix: host.cidr
          defaultOutboundAccess: false
          networkSecurityGroup: { id: nsgs[i].id }
        }
      }
    ]
  }
}
// Explicit outbound access for package/model downloads. GPU inbound is denied by its NSG.
resource publicIps 'Microsoft.Network/publicIPAddresses@2024-05-01' = [
  for host in hosts: {
    name: '${prefix}-${host.role}-pip'
    location: location
    tags: tags
    sku: { name: 'Standard' }
    properties: { publicIPAllocationMethod: 'Static' }
  }
]
resource nics 'Microsoft.Network/networkInterfaces@2024-05-01' = [
  for (host, i) in hosts: {
    name: '${prefix}-${host.role}-nic'
    location: location
    tags: tags
    properties: {
      ipConfigurations: [
        {
          name: 'primary'
          properties: {
            privateIPAllocationMethod: 'Static'
            privateIPAddress: host.ip
            subnet: { id: '${vnet.id}/subnets/${host.subnet}' }
            publicIPAddress: { id: publicIps[i].id }
          }
        }
      ]
    }
  }
]
resource dataDisks 'Microsoft.Compute/disks@2024-03-02' = [
  for host in hosts: {
    name: '${prefix}-${host.role}-data'
    location: location
    tags: tags
    sku: { name: 'StandardSSD_LRS' }
    properties: { creationData: { createOption: 'Empty' }, diskSizeGB: 128 }
  }
]
resource vms 'Microsoft.Compute/virtualMachines@2024-07-01' = [
  for (host, i) in hosts: {
    name: '${prefix}-${host.role}'
    location: location
    tags: tags
    properties: {
      hardwareProfile: { vmSize: host.size }
      osProfile: {
        computerName: '${prefix}-${host.role}'
        adminUsername: adminUsername
        linuxConfiguration: {
          disablePasswordAuthentication: true
          ssh: { publicKeys: [{ path: '/home/${adminUsername}/.ssh/authorized_keys', keyData: sshPublicKey }] }
        }
      }
      storageProfile: {
        imageReference: {
          publisher: 'Canonical'
          offer: 'ubuntu-24_04-lts'
          sku: 'server'
          version: ubuntuImageVersion
        }
        osDisk: {
          createOption: 'FromImage'
          diskSizeGB: 64
          deleteOption: 'Detach'
          managedDisk: { storageAccountType: 'StandardSSD_LRS' }
        }
        dataDisks: [
          {
            lun: 0
            createOption: 'Attach'
            deleteOption: 'Detach'
            caching: 'None'
            managedDisk: { id: dataDisks[i].id }
          }
        ]
      }
      networkProfile: { networkInterfaces: [{ id: nics[i].id, properties: { primary: true } }] }
    }
  }
]
output appPublicIp string = publicIps[0].properties.ipAddress
output gpuPrivateIp string = hosts[1].ip
output gpuVmName string = vms[1].name
